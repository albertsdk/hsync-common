"""Tests for hsync_common.clock."""

from unittest.mock import patch

import pytest

from hsync_common.clock import (
    CLOCK_SKEW_THRESHOLD,
    compute_clock_offset,
    measure_clock_offset,
)


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


class TestThreshold:
    def test_threshold_is_positive_number(self):
        assert isinstance(CLOCK_SKEW_THRESHOLD, (int, float))
        assert CLOCK_SKEW_THRESHOLD > 0


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

    def test_timestamp_string_is_coerced_to_float(self):
        getter = _FakeGet(_FakeResponse(200, {"timestamp": "110.5"}))
        with patch("hsync_common.clock.time.time", side_effect=[100.0, 101.0]):
            result = measure_clock_offset("http://srv/api/v1/time", http_get=getter)
        assert result is not None
        assert result[0] == pytest.approx(10.0)

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
