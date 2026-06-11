# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for hsync_common.format."""

import pytest

from hsync_common.format import format_bytes, format_duration


class TestFormatBytes:
    def test_bytes_render_as_integer(self):
        assert format_bytes(0) == "0 B"
        assert format_bytes(500) == "500 B"
        assert format_bytes(1023) == "1023 B"

    def test_kilobytes(self):
        assert format_bytes(1024) == "1.0 KB"
        assert format_bytes(1536) == "1.5 KB"

    def test_megabytes_and_gigabytes(self):
        assert format_bytes(1024 * 1024) == "1.0 MB"
        assert format_bytes(int(1.5 * 1024 * 1024 * 1024)) == "1.5 GB"

    def test_decimals_param(self):
        assert format_bytes(1536, decimals=2) == "1.50 KB"

    def test_negative(self):
        assert format_bytes(-2048) == "-2.0 KB"

    def test_largest_unit(self):
        huge = 1024**9  # beyond YB scale collapses onto YB
        assert format_bytes(huge).endswith(" YB")


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
