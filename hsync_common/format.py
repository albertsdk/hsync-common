# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Human-readable formatting helpers shared across HSYNC projects.

Provides the canonical implementations for:

- :func:`format_bytes` - render a byte count using binary (1024-based) units.
- :func:`parse_size` - parse a human-readable size (``"500MB"``, ``"2GB"``)
  back into bytes, the inverse of :func:`format_bytes`.
- :func:`format_duration` - render a number of seconds either as a compact
  ``"1h 5m 30s"`` style string or as a ``"1:05:30"`` clock style string.
"""

from __future__ import annotations

import re

# Binary (1024-based) size units, from bytes up to yottabytes.
_BYTE_UNITS: tuple[str, ...] = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")

# Size suffixes accepted by :func:`parse_size`, mapped to their binary
# multiplier. The ``iB`` (``KiB``…) and short (``K``…) spellings are aliases of
# the same 1024-based multiples: every HSYNC surface is binary
# (``format_bytes``, ``--limit-upload``, the free-space reserve), so there is no
# decimal-MB ambiguity to preserve and a user who writes ``500MiB`` must not be
# rejected for being *more* precise.
_SIZE_MULTIPLIERS: dict[str, int] = {
    "B": 1,
    "K": 1024,
    "KB": 1024,
    "KIB": 1024,
    "M": 1024**2,
    "MB": 1024**2,
    "MIB": 1024**2,
    "G": 1024**3,
    "GB": 1024**3,
    "GIB": 1024**3,
    "T": 1024**4,
    "TB": 1024**4,
    "TIB": 1024**4,
}

# ``<number><optional space><unit>``; the unit is validated separately so an
# unknown suffix gets its own error message.
_SIZE_RE = re.compile(r"^(?P<number>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>[A-Za-z]*)$")


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
    fmt = f".{decimals}f"
    for unit in _BYTE_UNITS[:-1]:
        if abs(value) < 1024:
            if unit == "B":
                return f"{int(value)}{unit}"
            return format(value, fmt) + unit
        value /= 1024
    return format(value, fmt) + _BYTE_UNITS[-1]


def parse_size(raw: str | int, *, require_unit: bool = False) -> int:
    """Parse a human-readable size into bytes (inverse of :func:`format_bytes`).

    Accepted forms: ``500`` (bytes, only when *require_unit* is false), ``0``,
    ``"0"``, ``"0B"``, ``"500B"``, ``"500KB"``, ``"500 MB"``, ``"1.5GB"``,
    ``"2TiB"``. Units are binary (``1KB = 1024B``) and case-insensitive; the
    short (``K``) and ``iB`` (``KiB``) spellings are aliases of the same
    multiple. Fractions are truncated to whole bytes.

    Args:
        raw: Size as an integer byte count or a human-readable string.
        require_unit: Reject a non-zero string without a unit. Operator-facing
            settings enable it so a bare ``500`` cannot be silently read as
            500 bytes when the user meant 500 MB; ``0`` (disabled) is always
            accepted.

    Returns:
        The size in bytes (``>= 0``).

    Raises:
        ValueError: If the value is empty, negative, malformed, carries an
            unknown unit, or lacks a unit while *require_unit* is set.

    Consumers: ``hsync-client`` (``--min-free-disk-space``, ``--limit-upload``),
    ``hsync-server`` (``HSYNC_MIN_FREE_DISK_SPACE``), ``hsync-desktop``
    (settings/wizard validation), shared tests.
    """
    if isinstance(raw, bool):
        # bool is an int subclass; True must never mean "1 byte".
        raise ValueError(f"Invalid size: {raw!r}")
    if isinstance(raw, int):
        if raw < 0:
            raise ValueError(f"Size must not be negative, got {raw}")
        return raw

    text = str(raw).strip()
    if not text:
        raise ValueError("Size is empty")
    match = _SIZE_RE.match(text)
    if match is None:
        raise ValueError(f"Invalid size {raw!r} (expected e.g. '500MB')")

    number = float(match.group("number"))
    unit = match.group("unit").upper()
    if not unit:
        if number == 0:
            return 0
        if not number.is_integer() or require_unit:
            # A bare fraction has no meaning in bytes; a bare integer is only
            # accepted where the caller does not require an explicit unit.
            raise ValueError(f"Size {raw!r} is missing a unit (expected e.g. '500MB')")
        return int(number)

    multiplier = _SIZE_MULTIPLIERS.get(unit)
    if multiplier is None:
        raise ValueError(
            f"Unknown size unit {match.group('unit')!r} in {raw!r} (use B, KB, MB, GB or TB)"
        )
    return int(number * multiplier)


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

    seconds = max(seconds, 0.0)

    if subsecond and style == "compact" and seconds < 60:
        if seconds < 1:
            return f"{int(seconds * 1000)}ms"
        return f"{seconds:.1f}s"

    total = int(seconds)

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
