# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Clock-skew measurement utilities shared between HSYNC client and server.

HSYNC relies on the operating-system time synchronisation (NTP, e.g. chrony,
systemd-timesyncd or the Windows Time service) for correct file timestamps:
``mtime`` travels with the file as metadata, so it is consistent across peers,
but the *direction* of a sync is decided by comparing timestamps. A large
clock offset between two machines that edit the same file close in time can
therefore lead to an incorrect winner.

These helpers implement an NTP-like round-trip measurement against the
server/master ``/api/v1/time`` endpoint. They are purely diagnostic: the
offset is surfaced as a warning so the operator can fix the system clock; it
is never silently applied to rewrite timestamps (which would be unreliable in
multi-peer topologies).
"""

import time
from typing import Protocol

# Clock skew warning threshold in seconds. Offsets above this value are
# surfaced as a warning to the operator.
CLOCK_SKEW_THRESHOLD = 5.0


class _TimeResponse(Protocol):
    """Minimal HTTP response shape required by :func:`measure_clock_offset`."""

    status_code: int

    def json(self) -> dict: ...


class _HttpGet(Protocol):
    """Callable performing an HTTP GET (e.g. ``requests.get``)."""

    def __call__(self, url: str, **kwargs) -> _TimeResponse: ...


def compute_clock_offset(t1: float, t2: float, t3: float) -> tuple[float, float]:
    """
    Compute the NTP-like clock offset and round-trip time.

    Args:
        t1: Local time immediately before the request.
        t2: Remote time reported by the server (``/api/v1/time``).
        t3: Local time immediately after the response.

    Returns:
        Tuple ``(offset, rtt)`` in seconds. ``offset`` is positive when the
        remote clock is ahead of the local one.
    """
    rtt = t3 - t1
    offset = t2 - (t1 + rtt / 2)
    return offset, rtt


def measure_clock_offset(
    time_url: str,
    *,
    http_get: _HttpGet,
    headers: dict | None = None,
    verify: bool = True,
    timeout: float = 30,
) -> tuple[float, float] | None:
    """
    Measure the clock offset against a ``/api/v1/time`` endpoint.

    Performs a single round-trip GET using the injected ``http_get`` callable
    (so this module stays free of any HTTP dependency) and returns the
    estimated offset. Network errors are *not* caught here: the caller decides
    how to handle them (typically a debug log).

    Args:
        time_url: Full URL of the time endpoint.
        http_get: Callable performing the GET (e.g. ``requests.get``).
        headers: Optional request headers.
        verify: TLS certificate verification flag passed to ``http_get``.
        timeout: Request timeout in seconds.

    Returns:
        Tuple ``(offset, rtt)`` in seconds, or ``None`` if the endpoint did
        not return HTTP 200 or omitted the ``timestamp`` field.
    """
    t1 = time.time()
    response = http_get(time_url, headers=headers or {}, verify=verify, timeout=timeout)
    t3 = time.time()

    if response.status_code != 200:
        return None

    t2 = response.json().get("timestamp")
    if t2 is None:
        return None

    return compute_clock_offset(t1, float(t2), t3)
