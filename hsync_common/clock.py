# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Clock-offset measurement utilities shared by every HSYNC project.

HSYNC keeps the wall clock out of *causal* decisions (vector clocks, ADR-0022),
but the tie-break for a true concurrent divergence is chronological: the
``corrected_mtime`` of each version decides which content keeps the original
path and which one is preserved as a ``_conflicted_copy_`` (ADR-0023). For that
timestamp to be comparable across machines the local clock must be corrected by
the offset measured against a trusted reference:

* **Client-server mode** — the server/master is the time authority:
  :func:`measure_clock_offset` performs an NTP-like HTTP round-trip against the
  ``/api/v1/time`` endpoint (``compute_clock_offset`` is the shared math).

* **p2p / no-server startup** — :func:`measure_clock_offset_ntp_multi`
  probes a configurable list of public SNTP servers (UDP, RFC 4330) in order
  until one answers; the estimate is the median of several round-trips.

* **Offline / air-gapped** — every probe fails: the caller records offset 0 and
  logs a degraded-temporal-mode warning; synchronisation must proceed.

The measured offset (remote clock − local clock) is process-local and consumed
through the :class:`ClockOffsetStore` singleton: ``correct_mtime(mtime)``
returns ``mtime + offset`` (int). Measurements are never persisted and never
write the system clock. Wire-supplied offsets/timestamps are *clamped* by
:func:`clamp_wire_corrected_mtime` so a far-future peer value cannot win every
tie-break (conflict engineering).

Consumers: ``hsync-client`` (startup probing, mtime correction on
self-record/advertising), ``hsync-server`` (clamping of incoming upload
metadata), ``hsync-android`` (``TimeSync.kt`` mirror) and the shared fixtures.
"""

import math
import socket
import struct
import time
from statistics import median
from typing import Protocol

from .constants import (
    CORRECTED_MTIME_MAX_FUTURE_SKEW,
    NTP_DEFAULT_HOSTS,
    NTP_PORT,
    NTP_PROBES_PER_HOST,
    NTP_TIMEOUT_SECONDS,
)
from .endpoint import parse_host_port

# Seconds between NTP epoch (1900-01-01) and Unix epoch (1970-01-01).
_NTP_EPOCH_DELTA = 2_208_988_800

__all__ = [
    "ClockOffsetStore",
    "HttpGet",
    "TimeResponse",
    "clamp_incoming_corrected_mtime",
    "clamp_wire_corrected_mtime",
    "compute_clock_offset",
    "correct_mtime",
    "measure_clock_offset",
    "measure_clock_offset_ntp",
    "measure_clock_offset_ntp_multi",
    "now_corrected",
    "offset_store",
    "parse_ntp_hosts",
    "parse_ntp_targets",
]


# ─────────────────────────────────────────────────────────────────────────────
# Offset math (shared by the HTTP and SNTP probes)
# ─────────────────────────────────────────────────────────────────────────────


def compute_clock_offset(t1: float, t2: float, t3: float) -> tuple[float, float]:
    """
    Compute the NTP-like clock offset and round-trip time.

    Args:
        t1: Local time immediately before the request.
        t2: Remote time reported by the peer (``/api/v1/time`` or SNTP).
        t3: Local time immediately after the response.

    Returns:
        Tuple ``(offset, rtt)`` in seconds. ``offset`` is positive when the
        remote clock is ahead of the local one.
    """
    rtt = t3 - t1
    offset = t2 - (t1 + rtt / 2)
    return offset, rtt


# ─────────────────────────────────────────────────────────────────────────────
# HTTP probe (server/master time authority, client-server mode)
# ─────────────────────────────────────────────────────────────────────────────


class TimeResponse(Protocol):
    """Minimal HTTP response shape required by :func:`measure_clock_offset`."""

    status_code: int

    def json(self) -> dict: ...


class HttpGet(Protocol):
    """Callable performing an HTTP GET (e.g. ``requests.get``)."""

    def __call__(self, url: str, **kwargs) -> TimeResponse: ...


def measure_clock_offset(
    time_url: str,
    *,
    http_get: HttpGet,
    headers: dict | None = None,
    verify: bool = True,
    timeout: float = 30,
) -> tuple[float, float] | None:
    """
    Measure the clock offset against a ``/api/v1/time`` endpoint.

    Performs a single round-trip GET using the injected ``http_get`` callable
    (so this module stays free of any HTTP dependency) and returns the
    estimated offset. Network errors are *not* caught here: the caller decides
    how to handle them (typically a debug log and offset 0).

    Args:
        time_url: Full URL of the time endpoint.
        http_get: Callable performing the GET (e.g. ``requests.get``).
        headers: Optional request headers.
        verify: TLS certificate verification flag passed to ``http_get``.
        timeout: Request timeout in seconds.

    Returns:
        Tuple ``(offset, rtt)`` in seconds, or ``None`` if the endpoint did
        not return HTTP 200 or the ``timestamp`` field was missing, not a
        finite number and not numeric-string coercible (a malformed payload
        must degrade the measurement, never crash the caller).
    """
    t1 = time.time()
    response = http_get(time_url, headers=headers or {}, verify=verify, timeout=timeout)
    t3 = time.time()

    if response.status_code != 200:
        return None

    raw_t2 = response.json().get("timestamp")
    if raw_t2 is None or isinstance(raw_t2, bool):
        # Missing key or JSON null/bool: no usable remote timestamp.
        return None
    try:
        t2 = float(raw_t2)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(t2):
        # json.loads accepts Infinity/NaN: a non-finite timestamp would
        # produce a meaningless offset.
        return None

    return compute_clock_offset(t1, t2, t3)


# ─────────────────────────────────────────────────────────────────────────────
# SNTP probe (UDP, RFC 4330 — p2p / no-server startup)
# ─────────────────────────────────────────────────────────────────────────────


def parse_ntp_hosts(value: str | None) -> tuple[str, ...]:
    """Parse the ``HSYNC_NTP_HOSTS`` CSV value into a non-empty raw-entry tuple.

    Entries are returned **verbatim** (``host``, ``host:port``, ``[IPv6]``,
    ``[IPv6]:port`` — no validation here): the canonical, validated form is
    :func:`parse_ntp_targets`. Empty/blank entries are skipped; ``None`` or an
    all-blank value returns the defaults from
    :data:`hsync_common.constants.NTP_DEFAULT_HOSTS`.
    Consumers: ``hsync-client`` (config layer), ``hsync-android`` mirror.
    """
    if value is None:
        return NTP_DEFAULT_HOSTS
    hosts = tuple(h.strip() for h in value.split(",") if h.strip())
    return hosts or NTP_DEFAULT_HOSTS


def parse_ntp_targets(value: str | None) -> tuple[tuple[str, int], ...]:
    """Parse ``HSYNC_NTP_HOSTS`` into ``(host, port)`` targets.

    Each CSV entry is a ``HOST[:PORT]`` endpoint parsed by the shared
    :func:`hsync_common.endpoint.parse_host_port` SSOT: ``host`` (default SNTP
    port), ``host:port``, ``[IPv6]`` or ``[IPv6]:port``. Malformed entries
    (invalid port, invalid host, URL-like input) are dropped with their host;
    ``None``/blank falls back to the default hosts on the standard port.

    Consumers: ``hsync-client`` (``timesync`` probe), ``hsync-android``
    (``TimeSync.ntpTargets`` mirror) and the shared fixtures.
    """
    targets: list[tuple[str, int]] = []
    for entry in parse_ntp_hosts(value):
        try:
            endpoint = parse_host_port(entry)
        except ValueError:
            continue
        targets.append((endpoint.host, endpoint.port or NTP_PORT))
    if not targets:
        # Every entry carried a malformed endpoint: fall back to the defaults on
        # the standard port — the same never-empty contract as parse_ntp_hosts.
        return tuple((h, NTP_PORT) for h in NTP_DEFAULT_HOSTS)
    return tuple(targets)


def _unix_to_ntp64(unix_epoch: float) -> tuple[int, int]:
    """Convert Unix epoch seconds to the 64-bit NTP timestamp (whole, fraction)."""
    seconds = unix_epoch + _NTP_EPOCH_DELTA
    whole = int(seconds)
    fraction = int((seconds - whole) * (1 << 32))
    return whole & 0xFFFFFFFF, fraction & 0xFFFFFFFF


def _ntp64_to_unix(whole: int, fraction: int) -> float:
    """Convert a 64-bit NTP timestamp (whole, fraction) to Unix epoch seconds."""
    return (whole + fraction / (1 << 32)) - _NTP_EPOCH_DELTA


def _build_sntp_client_packet() -> bytes:
    """Build a 48-byte SNTP client request (version 4, client mode)."""
    whole, fraction = _unix_to_ntp64(time.time())
    # LI=0, VN=4, Mode=3 (client) = 0b00_100_011 = 0x23; transmit timestamp at
    # bytes 40-47 lets us match the response and compute the round-trip.
    return b"\x23" + b"\x00" * 39 + struct.pack("!II", whole, fraction)


def _parse_sntp_response(packet: bytes, t1: float, t4: float) -> tuple[float, float] | None:
    """Parse an SNTP server reply; return ``(offset, rtt)`` or ``None``.

    Rejects truncation, non-server replies (mode != 4) and stratum 0
    (Kiss-o'-Death): any unusable reply degrades the measurement to ``None``.
    """
    if len(packet) < 48:
        return None
    mode = packet[0] & 0x07
    stratum = packet[1]
    if mode != 4 or stratum == 0:
        return None
    t3_whole, t3_fraction = struct.unpack("!II", packet[40:48])
    t3 = _ntp64_to_unix(t3_whole, t3_fraction)
    if not math.isfinite(t3):
        return None
    return compute_clock_offset(t1, t3, t4)


def _sntp_probe_once(host: str, *, port: int, timeout: float) -> tuple[float, float] | None:
    """Perform one SNTP round-trip to *host*; returns ``(offset, rtt)`` or ``None``.

    The socket is *connected* before the exchange: the kernel then surfaces an
    ICMP port/host-unreachable as an immediate ``ECONNREFUSED`` instead of
    blocking ``recv`` for the whole timeout, so a dead endpoint fails fast
    (one refused probe costs ~0s, not *timeout* seconds), and datagrams from
    any other source are filtered out (no stray-packet spoofing of the clock).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            packet = _build_sntp_client_packet()
            t1 = time.time()
            sock.send(packet)
            reply = sock.recv(48)
            t4 = time.time()
    except OSError:
        # timeouts, refused/unreachable hosts, DNS failures: caller moves on.
        return None
    return _parse_sntp_response(reply, t1, t4)


def measure_clock_offset_ntp(
    host: str,
    *,
    port: int = NTP_PORT,
    timeout: float = NTP_TIMEOUT_SECONDS,
    probes: int = NTP_PROBES_PER_HOST,
) -> tuple[float, float] | None:
    """Measure the clock offset against a single SNTP server.

    Runs ``probes`` round-trips and returns the **median** offset so a single
    jittery reply cannot bias the estimate. The first successful probe is
    enough only when ``probes`` is 1; otherwise every reply must parse.

    Returns:
        Tuple ``(offset, rtt)`` in seconds (``offset`` positive when the
        remote clock is ahead of the local one), or ``None`` when the server
        is unreachable or every reply was unusable.
    """
    results: list[tuple[float, float]] = []
    for _ in range(max(1, probes)):
        probe = _sntp_probe_once(host, port=port, timeout=timeout)
        if probe is None:
            continue
        results.append(probe)
    if not results:
        return None
    return float(median(r[0] for r in results)), float(median(r[1] for r in results))


def measure_clock_offset_ntp_multi(
    hosts: tuple[str, ...] | tuple[tuple[str, int], ...] = NTP_DEFAULT_HOSTS,
    *,
    port: int = NTP_PORT,
    timeout: float = NTP_TIMEOUT_SECONDS,
    probes: int = NTP_PROBES_PER_HOST,
) -> tuple[float, float, str] | None:
    """Probe *hosts* in order until one answers; return ``(offset, rtt, host)``.

    Each entry may be a bare host (probed on *port*) or a ``(host, port)``
    pair (per-host port override). Returns ``None`` when every host fails
    (offline/air-gapped): the caller records offset 0 and logs degraded
    temporal-mode operation.
    """
    for entry in hosts:
        if isinstance(entry, tuple):
            host, host_port = entry
        else:
            host, host_port = entry, port
        result = measure_clock_offset_ntp(host, port=host_port, timeout=timeout, probes=probes)
        if result is not None:
            return result[0], result[1], host
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Process-local offset store & mtime correction
# ─────────────────────────────────────────────────────────────────────────────


class ClockOffsetStore:
    """Process-local holder of the measured clock offset (remote − local).

    Measured at startup (or handshake) and consumed through
    :meth:`correct_mtime` every time a local version is self-recorded or
    advertised. :meth:`begin_epoch` / :meth:`end_epoch` freeze the basis for
    one sync cycle so a late background measurement cannot mix clocks
    mid-cycle. The offset is never persisted: a stale value is harmless
    because it is re-measured on every process start.

    Consumers: ``hsync-client`` (all three transport modes), ``hsync-server``
    (clamping reference), ``hsync-android`` (``TimeSync.kt`` mirror).
    """

    def __init__(self) -> None:
        self._offset: float | None = None
        self._epoch_active = False
        self._epoch_offset: float | None = None

    def record(self, offset: float) -> None:
        """Store the measured offset."""
        self._offset = float(offset)

    def begin_epoch(self) -> None:
        """Freeze the offset used by ``correct_mtime`` until :meth:`end_epoch`.

        A later :meth:`record` still updates the live measurement (so the next
        epoch sees it), but this epoch keeps a single basis. Consumer:
        ``hsync-client`` ``sync()`` — a background LAN NTP probe must not
        change ``corrected_mtime`` mid-cycle.
        """
        self._epoch_offset = self._offset
        self._epoch_active = True

    def end_epoch(self) -> None:
        """Release the frozen epoch so ``correct_mtime`` follows the live offset."""
        self._epoch_active = False
        self._epoch_offset = None

    def get(self) -> float | None:
        """Return the stored offset (``None`` before any measurement)."""
        return self._offset

    def clear(self) -> None:
        """Forget the stored offset (used by tests and mode switches)."""
        self._offset = None
        self.end_epoch()

    def correct_mtime(self, mtime: int | float) -> int:
        """Return ``mtime + offset`` as int (raw ``mtime`` when unresolved)."""
        value = int(mtime)  # bool would collapse to 0/1; callers pass mtimes
        offset = self._epoch_offset if self._epoch_active else self._offset
        if offset is not None:
            return value + int(offset)
        return value

    def uncorrect_mtime(self, corrected_mtime: int | float) -> int:
        """Return ``corrected_mtime - offset`` as int (inverse of correct_mtime).

        A wire-supplied value is an ADR-0023 *corrected* time; writing it into
        the local filesystem requires the local raw clock, otherwise the next
        :func:`correct_mtime` re-adds the offset and the file stays divergent.
        """
        value = int(corrected_mtime)
        offset = self._epoch_offset if self._epoch_active else self._offset
        if offset is not None:
            return value - int(offset)
        return value


# Module-level singleton: one measurement per process, shared by every module
# that corrects timestamps (mirrored as a singleton in Android's TimeSync.kt).
offset_store = ClockOffsetStore()


def correct_mtime(mtime: int | float) -> int:
    """Correct *mtime* by the process offset (identity when unresolved).

    Consumers: ``hsync-client`` (``sync_state`` self-record, upload/listings
    version metadata), ``hsync-android`` mirror.
    """
    return offset_store.correct_mtime(mtime)


def uncorrect_mtime(corrected_mtime: int | float) -> int:
    """Convert a wire-supplied corrected mtime back to the local raw clock.

    Inverse of :func:`correct_mtime`. Consumers: ``hsync-client`` (adopting a
    peer's corrected mtime onto the local filesystem), ``hsync-client`` LAN
    master PATCH handler, ``hsync-android`` mirror.
    """
    return offset_store.uncorrect_mtime(corrected_mtime)


def now_corrected() -> float:
    """Current local time corrected by the process offset (clamping reference).

    The receiver-side guard of ADR-0023 measures a peer-supplied
    ``corrected_mtime`` against this reference: a value farther than
    ``CORRECTED_MTIME_MAX_FUTURE_SKEW`` in the future is clamped instead of
    being allowed to win every tie-break.

    Consumers: ``hsync-server`` (upload/delta-apply arbitration metadata),
    ``hsync-client`` (LAN master upload arbitration, remote decode),
    ``hsync-android`` (``TimeSync.kt`` mirror).
    """
    return offset_store.correct_mtime(time.time())


# ─────────────────────────────────────────────────────────────────────────────
# Wire-side clamping (conflict engineering)
# ─────────────────────────────────────────────────────────────────────────────


def clamp_wire_corrected_mtime(value: float, now_corrected: float) -> float:
    """Clamp a peer-supplied ``corrected_mtime`` to a sane upper bound.

    A far-future value announced by a malicious or wildly mis-set peer would
    win every mtime tie-break; values beyond ``now_corrected +
    CORRECTED_MTIME_MAX_FUTURE_SKEW`` are clamped to exactly that bound (never
    rejected, so the field still participates in comparisons).

    Consumers: ``hsync-server`` (upload arbitration metadata), ``hsync-client``
    (remote decode), ``hsync-android`` (``TimeSync.kt`` mirror).
    """
    return min(value, now_corrected + CORRECTED_MTIME_MAX_FUTURE_SKEW)


def clamp_incoming_corrected_mtime(value: float) -> float:
    """Clamp an incoming corrected mtime against this process's reference.

    Thin convenience wrapper over :func:`clamp_wire_corrected_mtime` that
    pins the reference to the local corrected clock
    (:func:`now_corrected`): the ADR-0023 receiver-side guard shared by every
    consuming hub (server upload/delta-apply, LAN master upload, client
    remote decode). A value of ``0`` (unknown) passes through unchanged.

    Consumers: ``hsync-server``, ``hsync-client``, ``hsync-android`` mirror.
    """
    if value <= 0:
        return 0.0
    return clamp_wire_corrected_mtime(value, now_corrected())
