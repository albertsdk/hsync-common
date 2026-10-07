# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for hsync_common.format."""

import pytest

from hsync_common.format import format_bytes, format_duration


class TestFormatBytes:
    def test_bytes_render_as_integer(self):
        assert format_bytes(0) == "0B"
        assert format_bytes(500) == "500B"
        assert format_bytes(1023) == "1023B"

    def test_kilobytes(self):
        assert format_bytes(1024) == "1.0KB"
        assert format_bytes(1536) == "1.5KB"

    def test_megabytes_and_gigabytes(self):
        assert format_bytes(1024 * 1024) == "1.0MB"
        assert format_bytes(int(1.5 * 1024 * 1024 * 1024)) == "1.5GB"

    def test_decimals_param(self):
        assert format_bytes(1536, decimals=2) == "1.50KB"

    def test_negative(self):
        assert format_bytes(-2048) == "-2.0KB"

    def test_largest_unit(self):
        huge = 1024**9  # beyond YB scale collapses onto YB
        assert format_bytes(huge).endswith("YB")


class TestFormatDuration:
    def test_none(self):
        assert format_duration(None) == ""

    def test_compact_seconds(self):
        assert format_duration(45) == "45s"

    def test_compact_minutes(self):
        assert format_duration(90) == "1m 30s"

    def test_compact_hours(self):
        assert format_duration(3725) == "1h 2m"

    def test_clock_under_hour(self):
        assert format_duration(90, style="clock") == "1:30"

    def test_clock_with_hours(self):
        assert format_duration(3725, style="clock") == "1:02:05"

    def test_negative_clamped(self):
        assert format_duration(-5) == "0s"

    def test_invalid_style(self):
        with pytest.raises(ValueError):
            format_duration(10, style="bogus")

    # ── subsecond=True ──────────────────────────────────────────────────

    def test_subsecond_milliseconds(self):
        assert format_duration(0.05, subsecond=True) == "50ms"
        assert format_duration(0.32, subsecond=True) == "320ms"
        assert format_duration(0.999, subsecond=True) == "999ms"

    def test_subsecond_seconds_with_decimal(self):
        assert format_duration(5.2, subsecond=True) == "5.2s"
        assert format_duration(59.9, subsecond=True) == "59.9s"

    def test_subsecond_boundary_at_one_second(self):
        # Exactly 1.0s renders as "1.0s" (decimal branch), not "1000ms"
        assert format_duration(1.0, subsecond=True) == "1.0s"

    def test_subsecond_minutes_unchanged(self):
        # ≥ 60s falls through to the compact format (no decimal)
        assert format_duration(90, subsecond=True) == "1m 30s"
        assert format_duration(3725, subsecond=True) == "1h 2m"

    def test_subsecond_zero(self):
        assert format_duration(0, subsecond=True) == "0ms"

    def test_subsecond_negative_clamped(self):
        assert format_duration(-5, subsecond=True) == "0ms"

    def test_subsecond_has_no_effect_on_clock_style(self):
        # subsecond only affects the compact style
        assert format_duration(0.5, style="clock", subsecond=True) == "0:00"
