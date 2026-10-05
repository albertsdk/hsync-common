"""Tests for hsync_common.clock."""

import socket
import struct
import threading
import time
from unittest.mock import patch

import pytest

from hsync_common.clock import (
    ClockOffsetStore,
    _ntp64_to_unix,
    _parse_sntp_response,
    _sntp_probe_once,
    _unix_to_ntp64,
    clamp_incoming_corrected_mtime,
    clamp_wire_corrected_mtime,
    compute_clock_offset,
    correct_mtime,
    measure_clock_offset,
    measure_clock_offset_ntp_multi,
    now_corrected,
    offset_store,
    parse_ntp_hosts,
    parse_ntp_targets,
    uncorrect_mtime,
)
from hsync_common.constants import NTP_DEFAULT_HOSTS


class _FakeResponse:
    """Minimal stand-in for an HTTP response."""

    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


class _FakeGet:
    """Callable recording its kwargs and returning a fixed response."""

    def __init__(self, response: _FakeResponse):
        self._response = response
        self.calls: list[dict] = []

    def __call__(self, url: str, **kwargs) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self._response


class TestComputeClockOffset:
    def test_no_skew_zero_offset(self):
        # Local midpoint equals remote time -> offset 0.
        offset, rtt = compute_clock_offset(t1=100.0, t2=100.5, t3=101.0)
        assert offset == pytest.approx(0.0)
        assert rtt == pytest.approx(1.0)

    def test_remote_ahead_positive_offset(self):
        offset, rtt = compute_clock_offset(t1=100.0, t2=110.5, t3=101.0)
        assert offset == pytest.approx(10.0)
        assert rtt == pytest.approx(1.0)

    def test_remote_behind_negative_offset(self):
        offset, _ = compute_clock_offset(t1=100.0, t2=90.5, t3=101.0)
        assert offset == pytest.approx(-10.0)

    def test_rtt_is_round_trip_duration(self):
        _, rtt = compute_clock_offset(t1=10.0, t2=10.0, t3=12.5)
        assert rtt == pytest.approx(2.5)


class TestMeasureClockOffset:
    def test_success_returns_offset_and_rtt(self):
        getter = _FakeGet(_FakeResponse(200, {"timestamp": 110.5}))
        with patch("hsync_common.clock.time.time", side_effect=[100.0, 101.0]):
            result = measure_clock_offset("http://srv/api/v1/time", http_get=getter)
        assert result is not None
        offset, rtt = result
        assert offset == pytest.approx(10.0)
        assert rtt == pytest.approx(1.0)

    def test_non_200_returns_none(self):
        getter = _FakeGet(_FakeResponse(503))
        result = measure_clock_offset("http://srv/api/v1/time", http_get=getter)
        assert result is None

    def test_missing_timestamp_returns_none(self):
        getter = _FakeGet(_FakeResponse(200, {}))
        result = measure_clock_offset("http://srv/api/v1/time", http_get=getter)
        assert result is None

    def test_null_timestamp_returns_none(self):
        # An explicit JSON null must exercise the None branch *inside* the
        # function (a missing key is already swallowed by dict.get).
        getter = _FakeGet(_FakeResponse(200, {"timestamp": None}))
        result = measure_clock_offset("http://srv/api/v1/time", http_get=getter)
        assert result is None

    def test_non_numeric_timestamp_returns_none(self):
        # A malformed payload must degrade to None, not crash in float().
        getter = _FakeGet(_FakeResponse(200, {"timestamp": "not-a-number"}))
        result = measure_clock_offset("http://srv/api/v1/time", http_get=getter)
        assert result is None

    def test_bool_timestamp_returns_none(self):
        # bool is an int subclass: True would coerce to a timestamp of 1.0.
        getter = _FakeGet(_FakeResponse(200, {"timestamp": True}))
        result = measure_clock_offset("http://srv/api/v1/time", http_get=getter)
        assert result is None

    def test_non_finite_timestamp_returns_none(self):
        # json.loads accepts Infinity/NaN: the offset would be meaningless.
        for bad in (float("inf"), float("-inf"), float("nan")):
            getter = _FakeGet(_FakeResponse(200, {"timestamp": bad}))
            result = measure_clock_offset("http://srv/api/v1/time", http_get=getter)
            assert result is None

    def test_timestamp_string_is_coerced_to_float(self):
        getter = _FakeGet(_FakeResponse(200, {"timestamp": "110.5"}))
        with patch("hsync_common.clock.time.time", side_effect=[100.0, 101.0]):
            result = measure_clock_offset("http://srv/api/v1/time", http_get=getter)
        assert result is not None
        assert result[0] == pytest.approx(10.0)

    def test_success_uses_computed_rtt(self):
        # Pin both outputs: the offset depends on the measured RTT, so a
        # regression in rtt computation must fail here.
        getter = _FakeGet(_FakeResponse(200, {"timestamp": 110.5}))
        with patch("hsync_common.clock.time.time", side_effect=[100.0, 101.0]):
            result = measure_clock_offset("http://srv/api/v1/time", http_get=getter)
        assert result is not None
        offset, rtt = result
        assert offset == pytest.approx(10.0)
        assert rtt == pytest.approx(1.0)

    def test_getter_receives_expected_kwargs(self):
        getter = _FakeGet(_FakeResponse(200, {"timestamp": 1.0}))
        headers = {"X-Client-Id": "abc"}
        measure_clock_offset(
            "http://srv/api/v1/time",
            http_get=getter,
            headers=headers,
            verify=False,
            timeout=12,
        )
        call = getter.calls[0]
        assert call["url"] == "http://srv/api/v1/time"
        assert call["headers"] == headers
        assert call["verify"] is False
        assert call["timeout"] == 12

    def test_default_headers_is_empty_dict(self):
        getter = _FakeGet(_FakeResponse(200, {"timestamp": 1.0}))
        measure_clock_offset("http://srv/api/v1/time", http_get=getter)
        assert getter.calls[0]["headers"] == {}

    def test_getter_exception_propagates(self):
        def _boom(url: str, **kwargs):
            raise RuntimeError("network down")

        with pytest.raises(RuntimeError):
            measure_clock_offset("http://srv/api/v1/time", http_get=_boom)


# ── SNTP / offset-store helpers (ADR-0023) ───────────────────────────────────


def _sntp_reply(server_unix: float, *, mode: int = 4, stratum: int = 2) -> bytes:
    """Build a 48-byte server-mode SNTP reply carrying *server_unix* in the
    transmit timestamp (bytes 40-47), like a real NTP server would."""
    whole, fraction = _unix_to_ntp64(server_unix)
    header = bytearray(48)
    header[0] = (4 << 3) | mode  # LI=0, VN=4, mode
    header[1] = stratum
    header[40:48] = struct.pack("!II", whole, fraction)
    return bytes(header)


class TestParseNtpHosts:
    def test_none_returns_defaults(self):
        assert parse_ntp_hosts(None) == NTP_DEFAULT_HOSTS

    def test_empty_and_blank_returns_defaults(self):
        assert parse_ntp_hosts("") == NTP_DEFAULT_HOSTS
        assert parse_ntp_hosts("  , , ") == NTP_DEFAULT_HOSTS

    def test_csv_is_split_and_stripped(self):
        assert parse_ntp_hosts(" one , two.example ,three ") == (
            "one",
            "two.example",
            "three",
        )

    def test_blank_entries_are_dropped(self):
        assert parse_ntp_hosts("one,,two") == ("one", "two")


class TestParseNtpTargets:
    def test_none_returns_defaults_on_standard_port(self):
        assert parse_ntp_targets(None) == tuple((h, 123) for h in NTP_DEFAULT_HOSTS)

    def test_host_port_overrides(self):
        assert parse_ntp_targets("stub.local:8123") == (("stub.local", 8123),)

    def test_mixed_entries(self):
        assert parse_ntp_targets("a.example, b.example:9000") == (
            ("a.example", 123),
            ("b.example", 9000),
        )

    def test_invalid_port_drops_entry(self):
        assert parse_ntp_targets("bad:notaport") == parse_ntp_targets("")

    def test_ipv6_bracketed_with_port(self):
        assert parse_ntp_targets("[::1]:8123") == (("::1", 8123),)

    def test_ipv6_bracketed_default_port(self):
        assert parse_ntp_targets("[2001:db8::1]") == (("2001:db8::1", 123),)

    def test_bare_ipv6_uses_default_port(self):
        assert parse_ntp_targets("::1") == (("::1", 123),)

    def test_invalid_host_dropped(self):
        assert parse_ntp_targets("my_host") == parse_ntp_targets("")

    def test_trailing_dot_host_dropped(self):
        assert parse_ntp_targets("pool.ntp.org.") == parse_ntp_targets("")


class TestNtp64RoundTrip:
    def test_unix_to_ntp_and_back(self):
        for unix in (0.0, 1_700_000_000.0, 1_700_000_000.5):
            whole, fraction = _unix_to_ntp64(unix)
            assert _ntp64_to_unix(whole, fraction) == pytest.approx(unix, abs=2**-32)


class TestParseSntpResponse:
    def test_server_reply_yields_offset_and_rtt(self):
        # t1=100.0 before request, remote=110.5, t4=101.0 after reply.
        reply = _sntp_reply(110.5)
        result = _parse_sntp_response(reply, t1=100.0, t4=101.0)
        assert result is not None
        offset, rtt = result
        assert offset == pytest.approx(10.0)
        assert rtt == pytest.approx(1.0)

    def test_truncated_reply_returns_none(self):
        assert _parse_sntp_response(b"\x23" * 10, t1=0.0, t4=1.0) is None

    def test_non_server_mode_returns_none(self):
        reply = _sntp_reply(100.0, mode=3)  # a client-mode reply is not a server answer
        assert _parse_sntp_response(reply, t1=0.0, t4=1.0) is None

    def test_kiss_of_death_returns_none(self):
        reply = _sntp_reply(100.0, stratum=0)  # Kiss-o'-Death ⇒ unusable
        assert _parse_sntp_response(reply, t1=0.0, t4=1.0) is None


class TestSntpProbeOnce:
    """Real loopback UDP round-trips (no mocks, internet-free)."""

    def test_live_stub_round_trip(self):
        """A loopback SNTP stub answering with a valid server reply yields a
        finite (offset, rtt) pair through the connected-socket path."""
        stub = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        stub.bind(("127.0.0.1", 0))
        stub.settimeout(5.0)
        port = stub.getsockname()[1]

        def _serve_one() -> None:
            try:
                _request, peer = stub.recvfrom(48)
                stub.sendto(_sntp_reply(time.time()), peer)
            except OSError:
                pass

        server = threading.Thread(target=_serve_one, daemon=True)
        server.start()
        try:
            result = _sntp_probe_once("127.0.0.1", port=port, timeout=5.0)
        finally:
            server.join(timeout=5.0)
            stub.close()
        assert result is not None
        offset, rtt = result
        assert abs(offset) < 5.0
        assert 0.0 <= rtt < 5.0

    def test_closed_port_fails_fast(self):
        """Regression: a dead endpoint must fail fast, not after the timeout.

        Test harnesses point ``HSYNC_NTP_HOSTS`` at a dead loopback port
        expecting an internet-free *fast* failure; an unconnected UDP socket
        instead blocked ``recvfrom`` until the timeout on every probe (3
        probes x ``NTP_TIMEOUT_SECONDS`` added ~9s to every LAN startup).
        """
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
        probe.close()

        started = time.monotonic()
        result = _sntp_probe_once("127.0.0.1", port=closed_port, timeout=2.0)
        elapsed = time.monotonic() - started

        assert result is None
        # ECONNREFUSED on loopback is ~instant; before the fix this took the
        # full 2.0s timeout. The 1.0s bound is generous for loaded CI hosts.
        assert elapsed < 1.0


class TestMeasureClockOffsetNtpMulti:
    def test_first_working_host_wins(self):
        """The probe stops at the first answering host and reports it."""

        def _fake_probe(host: str, *, port, timeout):
            if host == "good.example":
                return (10.0, 1.0)
            return None

        with patch("hsync_common.clock._sntp_probe_once", side_effect=_fake_probe):
            result = measure_clock_offset_ntp_multi(
                ("good.example", "other.example"), timeout=0.1, probes=1
            )
        assert result is not None
        assert result[2] == "good.example"

    def test_all_hosts_down_returns_none(self):
        """Offline/air-gapped: every SNTP host fails ⇒ None (caller records offset 0)."""
        with patch("hsync_common.clock._sntp_probe_once", return_value=None):
            result = measure_clock_offset_ntp_multi(
                ("down1.example", "down2.example"), timeout=0.1, probes=1
            )
        assert result is None

    def test_fallback_to_second_host(self):
        """When the first host is unreachable the next one is tried."""
        calls: list[str] = []

        def _fake_probe(host: str, *, port, timeout):
            calls.append(host)
            return (5.0, 1.0) if host == "second.example" else None

        with patch("hsync_common.clock._sntp_probe_once", side_effect=_fake_probe):
            result = measure_clock_offset_ntp_multi(
                ("first.example", "second.example"), timeout=0.1, probes=1
            )
        assert result is not None
        assert result[2] == "second.example"
        assert calls == ["first.example", "second.example"]


class TestClockOffsetStore:
    def test_unresolved_mtime_is_identity(self):
        store = ClockOffsetStore()
        assert store.correct_mtime(1234) == 1234

    def test_positive_offset_shifts_forward(self):
        store = ClockOffsetStore()
        store.record(10.0)
        assert store.get() == 10.0
        assert store.correct_mtime(100) == 110

    def test_negative_offset_shifts_backward(self):
        store = ClockOffsetStore()
        store.record(-6.0)
        assert store.correct_mtime(100) == 94

    def test_clear_forgets_measurement(self):
        store = ClockOffsetStore()
        store.record(4.0)
        store.clear()
        assert store.get() is None
        assert store.correct_mtime(100) == 100

    def test_module_singleton_correct_mtime(self):
        offset_store.clear()
        offset_store.record(7)
        try:
            assert correct_mtime(100) == 107
        finally:
            offset_store.clear()

    def test_zero_offset_is_degraded_mode_but_recorded(self):
        # Offline: offset 0 is still a recorded measurement so
        # mtimes flow through unmodified and sync proceeds.
        store = ClockOffsetStore()
        store.record(0.0)
        assert store.get() is not None
        assert store.correct_mtime(500) == 500

    def test_epoch_freezes_correct_mtime_across_later_record(self):
        """A mid-cycle record must not change corrected_mtime until end_epoch."""
        store = ClockOffsetStore()
        store.record(10.0)
        store.begin_epoch()
        store.record(50.0)
        assert store.get() == 50.0
        assert store.correct_mtime(100) == 110
        store.end_epoch()
        assert store.correct_mtime(100) == 150

    def test_epoch_unresolved_stays_identity_when_record_arrives_late(self):
        store = ClockOffsetStore()
        store.begin_epoch()
        store.record(12.0)
        assert store.correct_mtime(100) == 100
        store.end_epoch()
        assert store.correct_mtime(100) == 112

    def test_clear_ends_epoch(self):
        store = ClockOffsetStore()
        store.record(8.0)
        store.begin_epoch()
        store.clear()
        store.record(3.0)
        assert store.correct_mtime(100) == 103


class TestClampWireCorrectedMtime:
    def test_within_skew_kept(self):
        assert clamp_wire_corrected_mtime(1_000_000, 1_000_100) == 1_000_000

    def test_far_future_clamped(self):
        clamped = clamp_wire_corrected_mtime(10_000_000, 1_000_000)
        assert clamped == 1_000_000 + 300

    def test_past_value_kept(self):
        assert clamp_wire_corrected_mtime(999_000, 1_000_000) == 999_000


class TestClampIncomingCorrectedMtime:
    """ADR-0023 receiver-side guard wired into every consuming hub."""

    def test_unknown_zero_passes_through(self):
        # 0 means "the sender does not carry the field" — never clamp it.
        assert clamp_incoming_corrected_mtime(0) == 0

    def test_negative_passes_through_as_unknown(self):
        # Callers pre-filter negatives; the helper must not manufacture a
        # positive bound from a bogus input.
        assert clamp_incoming_corrected_mtime(-5) == 0

    def test_within_skew_kept(self):
        offset_store.clear()
        offset_store.record(0.0)
        try:
            now = int(now_corrected())
            assert clamp_incoming_corrected_mtime(float(now)) == now
        finally:
            offset_store.clear()

    def test_far_future_clamped_against_corrected_reference(self):
        offset_store.clear()
        offset_store.record(120.0)
        try:
            now = now_corrected()
            clamped = clamp_incoming_corrected_mtime(now + 10_000)
            assert clamped == pytest.approx(now + 300)
        finally:
            offset_store.clear()

    def test_offset_shifts_the_reference(self):
        # The guard measures the peer value against the *corrected* clock: an
        # offset of +500 s still clamps a +10 000 s value to now_corrected+300.
        offset_store.clear()
        offset_store.record(500.0)
        try:
            now = now_corrected()
            clamped = clamp_incoming_corrected_mtime(now + 10_000)
            assert clamped == pytest.approx(now + 300)
        finally:
            offset_store.clear()


class TestNowCorrected:
    def test_unresolved_now_is_raw_local_time(self):
        offset_store.clear()
        try:
            assert abs(now_corrected() - int(time.time())) <= 1
        finally:
            offset_store.clear()

    def test_offset_applied(self):
        offset_store.clear()
        offset_store.record(42.0)
        try:
            assert abs(now_corrected() - (int(time.time()) + 42)) <= 1
        finally:
            offset_store.clear()


class TestUncorrectMtime:
    """``uncorrect_mtime`` is the inverse of ``correct_mtime``."""

    def test_round_trip_with_offset(self):
        offset_store.clear()
        offset_store.record(3600.0)
        try:
            raw = 1_700_000_000
            assert correct_mtime(raw) == raw + 3600
            assert uncorrect_mtime(correct_mtime(raw)) == raw
        finally:
            offset_store.clear()

    def test_identity_without_offset(self):
        offset_store.clear()
        assert uncorrect_mtime(1_700_000_000) == 1_700_000_000
