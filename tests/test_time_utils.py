# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for hsync_common.time_utils — the SSOT timestamp module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hsync_common.time_utils import (
    conflict_timestamp,
    to_epoch,
    to_iso,
    utc_now_epoch,
    utc_now_iso,
)


# ---------------------------------------------------------------------------
# utc_now_*
# ---------------------------------------------------------------------------
class TestUtcNow:
    def test_utc_now_epoch_is_recent(self):
        t = utc_now_epoch()
        assert isinstance(t, int)
        # Within 10 seconds of now
        now = int(datetime.now(UTC).timestamp())
        assert abs(now - t) < 10

    def test_utc_now_iso_ends_with_z(self):
        s = utc_now_iso()
        assert isinstance(s, str)
        assert s.endswith("Z"), f"Expected Z suffix, got {s!r}"
        assert "T" in s
        # Round-trip: parse back
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        assert abs((now - parsed).total_seconds()) < 10

    def test_utc_now_iso_has_milliseconds(self):
        s = utc_now_iso()
        # Should have three decimal digits
        assert "." in s
        fractional = s.split(".")[1].rstrip("Z")
        assert len(fractional) == 3, f"Expected 3 ms digits, got {fractional!r}"


# ---------------------------------------------------------------------------
# to_iso
# ---------------------------------------------------------------------------
class TestToIso:
    EPOCH = 0  # 1970-01-01T00:00:00Z
    SOME_TIME = 1737360000  # 2025-01-20T08:00:00Z
    SOME_TIME_MS = 1737360000.123  # with ms

    def test_from_int_epoch(self):
        result = to_iso(self.SOME_TIME)
        assert result == "2025-01-20T08:00:00.000Z"
        assert result.endswith("Z")

    def test_from_float_epoch_with_ms(self):
        result = to_iso(self.SOME_TIME_MS)
        assert result == "2025-01-20T08:00:00.123Z"

    def test_from_datetime_with_tz(self):
        dt = datetime(2025, 1, 20, 8, 0, 0, 123000, tzinfo=UTC)
        result = to_iso(dt)
        assert result == "2025-01-20T08:00:00.123Z"

    def test_from_datetime_naive_raises(self):
        dt = datetime(2025, 1, 20, 8, 0, 0)
        with pytest.raises(ValueError, match="Naive datetime"):
            to_iso(dt)

    def test_custom_timespec(self):
        result = to_iso(self.SOME_TIME, timespec="seconds")
        assert result == "2025-01-20T08:00:00Z"

    def test_epoch_zero(self):
        result = to_iso(self.EPOCH)
        assert result == "1970-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# to_epoch
# ---------------------------------------------------------------------------
class TestToEpoch:
    SOME_EPOCH = 1737360000

    def test_from_none(self):
        assert to_epoch(None) is None

    def test_from_empty_string(self):
        assert to_epoch("") is None

    def test_from_whitespace_string(self):
        assert to_epoch("   ") is None

    def test_from_int(self):
        assert to_epoch(self.SOME_EPOCH) == self.SOME_EPOCH

    def test_from_float(self):
        assert to_epoch(1737360000.999) == 1737360000

    def test_from_float_truncates(self):
        # to_epoch truncates toward zero (int cast)
        assert to_epoch(1737360000.1) == 1737360000

    def test_from_digit_string(self):
        """Digit-only strings are parsed as Unix epoch seconds."""
        assert to_epoch("1737360000") == self.SOME_EPOCH

    def test_from_digit_string_negative(self):
        assert to_epoch("-3600") == -3600

    def test_from_digit_string_float(self):
        assert to_epoch("1737360000.5") == 1737360000

    def test_from_digit_string_with_sign(self):
        assert to_epoch("+1737360000") == self.SOME_EPOCH

    def test_from_iso_string_z(self):
        result = to_epoch("2025-01-20T08:00:00Z")
        assert result == self.SOME_EPOCH

    def test_from_iso_string_plus_zero(self):
        result = to_epoch("2025-01-20T08:00:00+00:00")
        assert result == self.SOME_EPOCH

    def test_from_iso_string_with_ms(self):
        result = to_epoch("2025-01-20T08:00:00.500Z")
        assert result == self.SOME_EPOCH  # truncated

    def test_from_iso_string_naive_assumes_utc(self):
        """Naive ISO strings are treated as UTC (not local time)."""
        result = to_epoch("2025-01-20T08:00:00")
        assert result == self.SOME_EPOCH

    def test_from_datetime_aware(self):
        dt = datetime(2025, 1, 20, 8, 0, 0, tzinfo=UTC)
        assert to_epoch(dt) == self.SOME_EPOCH

    def test_from_datetime_naive(self):
        """A naive datetime is treated as UTC (documented contract), matching
        the naive ISO-string path: the result is deterministic across hosts,
        independent of the test runner's local timezone (regression: the
        previous implementation delegated to .timestamp(), which interprets
        naive datetimes as LOCAL time)."""
        dt = datetime(2025, 1, 20, 8, 0, 0)
        result = to_epoch(dt)
        # 2025-01-20T08:00:00 UTC == the SOME_EPOCH constant.
        assert result == self.SOME_EPOCH

    def test_bool_rejected(self):
        with pytest.raises(TypeError, match="bool"):
            to_epoch(True)

    def test_bool_false_rejected(self):
        with pytest.raises(TypeError, match="bool"):
            to_epoch(False)

    def test_invalid_type(self):
        with pytest.raises(TypeError):
            to_epoch([1, 2, 3])  # type: ignore[arg-type]

    def test_invalid_string(self):
        with pytest.raises(ValueError):
            to_epoch("not-a-timestamp")

    def test_non_utc_tz_is_preserved(self):
        """A string with non-UTC offset is correctly converted to epoch."""
        # 2025-01-20T09:00:00+01:00 = 2025-01-20T08:00:00Z
        result = to_epoch("2025-01-20T09:00:00+01:00")
        assert result == self.SOME_EPOCH


# ---------------------------------------------------------------------------
# conflict_timestamp
# ---------------------------------------------------------------------------
class TestConflictTimestamp:
    def test_format(self):
        ts = conflict_timestamp(1737360000)
        assert ts == "20250120T080000Z"

    def test_no_colons_no_dashes(self):
        """Conflict timestamps must be filesystem-safe: no colons, no dashes
        beyond the T separator."""
        ts = conflict_timestamp(1737360000)
        assert ":" not in ts
        assert "-" not in ts

    def test_ends_with_z(self):
        ts = conflict_timestamp()
        assert ts.endswith("Z")

    def test_len_is_16(self):
        """YYYYMMDD + T + HHmmss + Z = 8+1+6+1 = 16 chars"""
        ts = conflict_timestamp(1737360000)
        assert len(ts) == 16

    def test_default_is_current_time(self):
        ts1 = conflict_timestamp()
        ts2 = conflict_timestamp()
        # Same second (or at most 1 sec apart due to function call overhead)
        # Just check the format is valid, not that they're equal.
        assert ts1.endswith("Z")
        assert ts2.endswith("Z")

    def test_from_datetime(self):
        dt = datetime(2025, 1, 20, 8, 0, 0, tzinfo=UTC)
        assert conflict_timestamp(dt) == "20250120T080000Z"

    def test_naive_datetime_raises(self):
        dt = datetime(2025, 1, 20, 8, 0, 0)
        with pytest.raises(ValueError, match="Naive datetime"):
            conflict_timestamp(dt)
