# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Human-readable formatting helpers shared across HSYNC projects.

Provides the canonical implementations for:

- :func:`format_bytes` - render a byte count using binary (1024-based) units.
- :func:`format_duration` - render a number of seconds either as a compact
  ``"1h 5m 30s"`` style string or as a ``"1:05:30"`` clock style string.
"""

from __future__ import annotations

# Binary (1024-based) size units, from bytes up to yottabytes.
_BYTE_UNITS: tuple[str, ...] = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")


def format_bytes(n: float, *, decimals: int = 1) -> str:
    """Format a byte count as a human-readable string using binary units.

    Bytes (``B``) are rendered as an integer; every larger unit is rendered
    with ``decimals`` decimal places. The unit is attached directly after the
    value with no separating space (e.g. ``"500B"``, ``"1.5MB"``) — the
    compact form used across logs and UI.

    Args:
        n: Number of bytes (may be negative).
        decimals: Number of decimal places for units larger than bytes.

    Returns:
        Human-readable string such as ``"1.5MB"`` or ``"500B"``.
    """
    value = float(n)
    for unit in _BYTE_UNITS[:-1]:
        if abs(value) < 1024:
            if unit == "B":
                return f"{int(value)}{unit}"
            return f"{value:.{decimals}f}{unit}"
        value /= 1024
    return f"{value:.{decimals}f}{_BYTE_UNITS[-1]}"


def format_duration(
    seconds: float | None, *, style: str = "compact", subsecond: bool = False
) -> str:
    """Format a number of seconds as a human-readable duration.

    Args:
        seconds: Duration in seconds. ``None`` yields an empty string.
        style: ``"compact"`` for ``"1h 5m 30s"`` style output, or ``"clock"``
            for ``"1:05:30"`` / ``"5:30"`` style output.
        subsecond: When ``True`` and ``style="compact"``, render sub-second
            durations with millisecond precision (``"120ms"``) and sub-minute
            durations with one decimal place (``"5.2s"``). Intended for
            short-lived operations such as file transfers where whole-second
            truncation would hide useful detail. Has no effect on the
            ``"clock"`` style or on durations of one minute or more.

    Returns:
        Human-readable duration string.

    Raises:
        ValueError: If ``style`` is not ``"compact"`` or ``"clock"``.
    """
    if seconds is None:
        return ""

    if seconds < 0:
        seconds = 0

    if subsecond and style == "compact" and seconds < 60:
        if seconds < 1:
            return f"{int(seconds * 1000)}ms"
        return f"{seconds:.1f}s"

    total = int(seconds)
    if total < 0:
        total = 0

    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)

    if style == "compact":
        if total < 60:
            return f"{secs}s"
        if total < 3600:
            return f"{minutes}m {secs}s"
        return f"{hours}h {minutes}m"

    if style == "clock":
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    raise ValueError(f"Invalid style: {style!r}. Must be 'compact' or 'clock'.")
