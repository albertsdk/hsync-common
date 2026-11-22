# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Canonical timestamp formatting and parsing for all HSYNC projects.

HSYNC uses **two representations** and converts between them through the
functions in this module, which is the single source of truth for every
timestamp operation:

* **Unix epoch seconds** (``int`` or ``float``) — the internal representation
  for file mtimes/ctimes, tombstones, peer tracking, rate limiting, and clock
  synchronisation. Always UTC by definition.

* **ISO 8601 with Z suffix** (``str``) — the interchange representation for
  JSON APIs, UI events, log output, and conflict-copy filenames.  The format
  is ``YYYY-MM-DDTHH:MM:SS.fffZ`` with millisecond precision for human-
  readable output and ``YYYYMMDDTHHmmssZ`` (compact, no delimiters except
  ``T`` and ``Z``) for filenames so they sort chronologically.

Consumers MUST import from this module and never reproduce a timestamp format
string or conversion inline.  Android/Kotlin projects mirror the same
contracts (see ``hsync-android``).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime


def utc_now_epoch() -> int:
    """Current UTC time as integer Unix epoch seconds."""
    return int(time.time())


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string with ``Z`` suffix and millisecond precision.

    Example: ``"2025-01-15T08:30:00.123Z"``.
    """
    return to_iso(datetime.now(UTC))


def _as_utc_dt(t: int | float | datetime) -> datetime:
    """Normalize an epoch timestamp or aware ``datetime`` to a UTC ``datetime``.

    Raises ``ValueError`` for a naive ``datetime`` (no timezone info).
    """
    if isinstance(t, datetime):
        if t.tzinfo is None:
            raise ValueError("Naive datetime without timezone is not accepted")
        return t
    return datetime.fromtimestamp(float(t), tz=UTC)


def to_iso(t: int | float | datetime, *, timespec: str = "milliseconds") -> str:
    """Convert an epoch timestamp or timezone-aware ``datetime`` to an ISO-8601
    string ending with ``Z``.

    Args:
        t: Unix epoch seconds (int or float) or a timezone-aware ``datetime``.
        timespec: Precision passed to ``datetime.isoformat()``
            (``"milliseconds"`` by default).

    Returns:
        ``"2025-01-15T08:30:00.123Z"`` style string.

    Raises:
        ValueError: If ``t`` is a naive ``datetime`` (no timezone info).
    """
    dt = _as_utc_dt(t)

    return dt.isoformat(timespec=timespec).replace("+00:00", "Z")


def to_epoch(t: str | int | float | datetime | None) -> int | None:
    """Parse various time representations into integer Unix epoch seconds.

    ``None``, empty strings, and whitespace-only strings return ``None``.
    Bool values are rejected (Python ``bool`` is a subclass of ``int``).

    Args:
        t: An ISO-8601 string, epoch seconds (int/float), or timezone-aware
            ``datetime``. Naive datetimes are treated as UTC.

    Returns:
        Integer epoch seconds, or ``None`` when the input is ``None``/empty.

    Raises:
        ValueError: If the input is a string that is not valid ISO 8601.
        OverflowError: If the epoch value is out of the supported range.
    """
    if t is None:
        return None
    if isinstance(t, bool):
        raise TypeError(f"Expected a timestamp, got bool ({t!r})")
    if isinstance(t, int):
        # Hot-path: epoch seconds are already an int (the dominant wire shape).
        return t

    if isinstance(t, datetime):
        if t.tzinfo is None:
            # Documented contract: naive datetimes are treated as UTC (the
            # same policy as naive ISO strings below). .timestamp() alone
            # would interpret a naive datetime as LOCAL time, silently
            # diverging between hosts in different timezones.
            t = t.replace(tzinfo=UTC)
        return int(t.timestamp())

    if isinstance(t, str):
        stripped = t.strip()
        if not stripped:
            return None

        # Strings that look like a number (possibly with a sign and an
        # optional fractional part) are Unix epoch seconds, not ISO-8601.
        # Parse them directly instead of feeding them to fromisoformat,
        # which would reject e.g. "1796465526" or "1796465526.5".
        looks_like_number = stripped.lstrip("-+").replace(".", "", 1).isdigit()
        if looks_like_number:
            return int(float(stripped))

        # ``datetime.fromisoformat`` accepts the ``Z`` suffix natively on the
        # supported Python (>= 3.12), so no normalization is needed.
        dt = datetime.fromisoformat(stripped)
        # If the parsed datetime is naive (no tzinfo), assume UTC.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp())

    if isinstance(t, float):
        return int(t)

    raise TypeError(f"Unsupported timestamp type: {type(t).__name__}")


def conflict_timestamp(t: int | float | datetime | None = None) -> str:
    """Return a compact, filesystem-safe timestamp for conflict-copy filenames.

    The format is ``YYYYMMDDTHHmmssZ`` (e.g. ``20250115T083000Z``) which sorts
    chronologically and contains no characters forbidden by any common
    filesystem.

    Args:
        t: Epoch seconds or timezone-aware ``datetime``.  Uses the current UTC
            time when omitted or ``None``.

    Returns:
        Compact timestamp string like ``"20250115T083000Z"``.
    """
    dt = datetime.now(UTC) if t is None else _as_utc_dt(t)

    return dt.strftime("%Y%m%dT%H%M%SZ")


# Wire format of the one-second-resolution ISO-8601 timestamp: the rendezvous
# emits ``ack.server_time`` with it and the client parses the same field, so the
# format string is defined once instead of being written on both sides of one
# protocol contract.
ISO_SECONDS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def to_iso_seconds(t: int | float | datetime) -> str:
    """Format *t* as the one-second ISO-8601 wire form ``...THH:MM:SSZ``.

    Consumers: ``hsync-rendezvous`` (``ack.server_time``).
    """
    return to_iso(t, timespec="seconds")


def parse_iso_seconds(value: object) -> datetime | None:
    """Parse the one-second ISO-8601 wire form, or ``None`` when it does not match.

    Strict by design (``strptime`` against :data:`ISO_SECONDS_FORMAT`): a
    malformed or higher-resolution value is rejected rather than silently
    accepted, since the recorded uncertainty assumes exactly this quantization.

    Consumers: ``hsync-client`` (``ack.server_time``).
    """
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, ISO_SECONDS_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_iso_dt(value: str) -> datetime:
    """Parse an ISO-8601 string into a UTC-aware ``datetime``.

    The ``Z`` suffix is accepted natively (supported Python), so callers no
    longer rewrite it to ``+00:00``; a naive value is treated as UTC.

    Raises:
        ValueError: If *value* is not valid ISO 8601.
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def quarantine_timestamp() -> str:
    """Compact **local-time** ``YYYYMMDD-HHMMSS`` stamp for quarantining corrupt data.

    Used to rename an unreadable state DB or settings blob (``...corrupt-<stamp>``)
    aside so the next run rebuilds it. Local time on purpose: it names a file an
    operator looks for next to the artifact, not a wire instant.

    Consumers: ``hsync-client`` (``state_reset``), ``hsync-desktop`` (shares store).
    """
    return datetime.now().strftime("%Y%m%d-%H%M%S")
