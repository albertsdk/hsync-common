# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for hsync_common.disk (free-space guard shared by every receiver)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hsync_common.disk import (
    BYTES_PER_MB,
    FreeSpaceCheck,
    check_free_space,
)


def _usage(free: int) -> SimpleNamespace:
    """Minimal ``shutil.disk_usage`` result."""
    return SimpleNamespace(total=free * 2, used=free, free=free)


class TestCheckFreeSpace:
    def test_disabled_reserve_never_probes(self):
        with patch("hsync_common.disk.disk_usage") as probe:
            result = check_free_space("/nowhere", reserve_bytes=0, incoming_bytes=10)

        assert result.ok is True
        assert result.error is None
        probe.assert_not_called()

    def test_ok_when_free_covers_reserve_plus_incoming(self):
        with patch("hsync_common.disk.disk_usage", return_value=_usage(1000)):
            result = check_free_space("/x", reserve_bytes=400, incoming_bytes=600)

        assert result.ok is True
        assert result.free_bytes == 1000
        assert result.required_bytes == 1000

    def test_rejects_when_incoming_breaks_the_reserve(self):
        # The reserve alone fits; reserve + payload does not.
        with patch("hsync_common.disk.disk_usage", return_value=_usage(1000)):
            result = check_free_space("/x", reserve_bytes=900, incoming_bytes=200)

        assert result.ok is False
        assert result.required_bytes == 1100

    def test_negative_incoming_is_clamped(self):
        with patch("hsync_common.disk.disk_usage", return_value=_usage(1000)):
            result = check_free_space("/x", reserve_bytes=500, incoming_bytes=-100)

        assert result.required_bytes == 500
        assert result.ok is True

    def test_probe_failure_is_a_warning_not_a_rejection(self):
        with patch("hsync_common.disk.disk_usage", side_effect=OSError("nope")):
            result = check_free_space("/x", reserve_bytes=10**18, incoming_bytes=1)

        assert result.ok is True
        assert result.error == "nope"
        assert result.free_bytes == 0

    def test_mb_properties_are_whole_megabytes(self):
        with patch("hsync_common.disk.disk_usage", return_value=_usage(3 * BYTES_PER_MB + 7)):
            result = check_free_space("/x", reserve_bytes=BYTES_PER_MB, incoming_bytes=0)

        assert result.free_mb == 3
        assert result.required_mb == 1


@pytest.mark.parametrize("disabled", [0, -1])
def test_non_positive_reserve_is_disabled(disabled):
    result = check_free_space("/x", reserve_bytes=disabled, incoming_bytes=10**9)
    assert isinstance(result, FreeSpaceCheck)
    assert result.ok is True


def test_module_does_not_require_the_path_to_exist(tmp_path):
    """``shutil.disk_usage`` resolves the mount, so a real dir works too."""
    result = check_free_space(str(tmp_path), reserve_bytes=1, incoming_bytes=0)

    assert result.error is None
    assert result.ok is True
    # The exact free byte count moves while other tests write to the same
    # filesystem, so only the decision and the plausibility are asserted.
    assert result.free_bytes > 0
    assert result.required_bytes == 1
