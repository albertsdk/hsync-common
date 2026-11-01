# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for the p2p delivery-progress frame (``file_progress``).

The master reports the bytes it received for a file a peer is uploading; the
uploading side renders them instead of its own transport counter.
"""

from __future__ import annotations

import pytest

from hsync_common.protocol.transfer_progress import (
    P2P_FILE_PROGRESS_TYPE,
    build_p2p_file_progress,
    validate_p2p_file_progress,
)


class TestBuild:
    """The builder emits the canonical wire shape."""

    def test_a_frame_carries_the_received_bytes(self):
        frame = build_p2p_file_progress(file="docs/report.bin", transferred=1024, total=4096)

        assert frame == {
            "type": "file_progress",
            "file": "docs/report.bin",
            "transferred": 1024,
            "total": 4096,
        }

    def test_the_type_is_the_wire_discriminator(self):
        assert P2P_FILE_PROGRESS_TYPE == "file_progress"
        assert build_p2p_file_progress(file="a.bin", transferred=1)["type"] == "file_progress"

    def test_an_unknown_total_is_zero(self):
        """A streamed body carries no per-part length: the sender keeps its own."""
        assert build_p2p_file_progress(file="a.bin", transferred=10)["total"] == 0

    @pytest.mark.parametrize(
        "file",
        ["", "../escape", "/etc/passwd", "a//b.bin", "a\\b"],
    )
    def test_an_unsafe_path_is_refused(self, file):
        with pytest.raises(ValueError):
            build_p2p_file_progress(file=file, transferred=1)


class TestValidate:
    """Malformed frames are rejected whole, never partially accepted."""

    @pytest.mark.parametrize(
        "value",
        [
            None,
            [],
            "file_progress",
            {"type": "file_progress", "file": "a.bin", "transferred": 1},
            {"type": "file_progress", "file": "a.bin", "transferred": 1, "total": 2, "extra": 1},
            {"type": "progress", "file": "a.bin", "transferred": 1, "total": 2},
            {"type": "file_progress", "file": "a.bin", "transferred": -1, "total": 2},
            {"type": "file_progress", "file": "a.bin", "transferred": 1.5, "total": 2},
            {"type": "file_progress", "file": "a.bin", "transferred": True, "total": 2},
            {"type": "file_progress", "file": "a.bin", "transferred": 3, "total": 2},
            {"type": "file_progress", "file": 42, "transferred": 1, "total": 2},
            {"type": "file_progress", "file": "../x", "transferred": 1, "total": 2},
        ],
    )
    def test_malformed_frames_are_rejected(self, value):
        assert validate_p2p_file_progress(value) is None

    def test_a_built_frame_round_trips(self):
        frame = build_p2p_file_progress(file="a.bin", transferred=1, total=2)

        assert validate_p2p_file_progress(dict(frame)) == frame

    def test_the_received_bytes_may_not_exceed_a_known_total(self):
        frame = {"type": "file_progress", "file": "a.bin", "transferred": 5, "total": 5}

        assert validate_p2p_file_progress(frame) is not None
