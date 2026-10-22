# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Unit tests for the shared ``.hsynckeep`` sentinel helpers."""

from __future__ import annotations

from hsync_common.constants import HSYNCKEEP_FILENAME
from hsync_common.models.sentinel import ensure_sentinel, is_sentinel_file, remove_empty_dir


class TestEnsureSentinel:
    def test_creates_the_marker_in_an_empty_dir(self, tmp_path):
        assert ensure_sentinel(tmp_path) is True
        assert (tmp_path / HSYNCKEEP_FILENAME).is_file()
        # A second call must not recreate/duplicate it.
        assert ensure_sentinel(tmp_path) is False

    def test_partial_artifacts_do_not_block_the_marker(self, tmp_path):
        (tmp_path / "f.part").write_text("x")
        assert ensure_sentinel(tmp_path) is True

    def test_skips_a_dir_with_a_syncable_entry(self, tmp_path):
        (tmp_path / "file.txt").write_text("x")
        assert ensure_sentinel(tmp_path) is False
        assert not (tmp_path / HSYNCKEEP_FILENAME).exists()

    def test_missing_dir_is_a_noop(self, tmp_path):
        assert ensure_sentinel(tmp_path / "missing") is False


class TestRemoveEmptyDir:
    def test_removes_an_empty_dir(self, tmp_path):
        target = tmp_path / "empty"
        target.mkdir()
        assert remove_empty_dir(target) is True
        assert not target.exists()

    def test_keeps_a_non_empty_dir(self, tmp_path):
        target = tmp_path / "full"
        target.mkdir()
        (target / "f").write_text("x")
        assert remove_empty_dir(target) is False
        assert target.exists()

    def test_never_removes_the_root(self, tmp_path):
        root = tmp_path / "bucket"
        root.mkdir()
        assert remove_empty_dir(root, keep_root=root) is False
        assert root.exists()

    def test_none_or_missing_path_is_a_noop(self, tmp_path):
        assert remove_empty_dir(None) is False
        assert remove_empty_dir(tmp_path / "missing") is False


class TestIsSentinelFile:
    def test_matches_the_marker_name(self):
        assert is_sentinel_file(f"/b/{HSYNCKEEP_FILENAME}") is True
        assert is_sentinel_file("/b/photo.jpg") is False
