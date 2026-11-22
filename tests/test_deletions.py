# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for the shared in-flight recursive-deletion registry."""

import pytest

from hsync_common.deletions import (
    begin_tree_delete,
    covered_by_tree_delete,
    end_tree_delete,
    reset_tree_deletes,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_tree_deletes()
    yield
    reset_tree_deletes()


class TestCoverage:
    def test_the_tree_root_itself_is_covered(self):
        begin_tree_delete("/bucket/Music")
        assert covered_by_tree_delete("/bucket/Music")

    def test_a_descendant_is_covered(self):
        begin_tree_delete("/bucket/Music")
        assert covered_by_tree_delete("/bucket/Music/Peter Gabriel/i_o/1.mp3")

    def test_a_trailing_slash_is_normalised(self):
        begin_tree_delete("/bucket/Music/")
        assert covered_by_tree_delete("/bucket/Music")
        assert covered_by_tree_delete("/bucket/Music/track.mp3")

    def test_a_sibling_prefix_is_not_covered(self):
        """Component-aware: /bucket/Music2 is not inside /bucket/Music."""
        begin_tree_delete("/bucket/Music")
        assert not covered_by_tree_delete("/bucket/Music2")
        assert not covered_by_tree_delete("/bucket/Music2/track.mp3")

    def test_a_parent_is_not_covered(self):
        begin_tree_delete("/bucket/Music/Crono")
        assert not covered_by_tree_delete("/bucket/Music")

    def test_an_unrelated_path_is_not_covered(self):
        begin_tree_delete("/bucket/Music")
        assert not covered_by_tree_delete("/bucket/Pictures/a.jpg")

    def test_ending_the_window_reopens_the_tree(self):
        begin_tree_delete("/bucket/Music")
        end_tree_delete("/bucket/Music/")
        assert not covered_by_tree_delete("/bucket/Music/track.mp3")

    def test_ending_an_unknown_tree_is_a_no_op(self):
        end_tree_delete("/bucket/Never")
        assert not covered_by_tree_delete("/bucket/Never")
