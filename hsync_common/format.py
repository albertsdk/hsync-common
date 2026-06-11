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
    with ``decimals`` decimal places. A single space separates the value and
    the unit (e.g. ``"500 B"``, ``"1.5 MB"``).

    Args:
        n: Number of bytes (may be negative).
        decimals: Number of decimal places for units larger than bytes.

    Returns:
        Human-readable string such as ``"1.5 MB"`` or ``"500 B"``.
    """
    value = float(n)
    for unit in _BYTE_UNITS[:-1]:
        if abs(value) < 1024:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.{decimals}f} {unit}"
        value /= 1024
    return f"{value:.{decimals}f} {_BYTE_UNITS[-1]}"


def format_duration(seconds: float | None, *, style: str = "compact") -> str:
    """Format a number of seconds as a human-readable duration.

    Args:
        seconds: Duration in seconds. ``None`` yields an empty string.
        style: ``"compact"`` for ``"1h 5m 30s"`` style output, or ``"clock"``
            for ``"1:05:30"`` / ``"5:30"`` style output.

    Returns:
        Human-readable duration string.

    Raises:
        ValueError: If ``style`` is not ``"compact"`` or ``"clock"``.
    """
    if seconds is None:
        return ""

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
