# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for hsync_common.listing (bucket listing shared by every surface)."""

import json
import os
from pathlib import Path

from hsync_common.listing import (
    file_entry,
    iter_bucket_entries,
    iter_dir_entries,
    iter_json_array,
    symlink_entry,
)
from hsync_common.models.dir import Dir
from hsync_common.models.file import File
from hsync_common.models.symlink import Symlink


def _write(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class TestIterJsonArray:
    def test_frames_an_empty_array(self):
        assert list(iter_json_array([])) == [b"[", b"]"]

    def test_frames_items_with_compact_encoding(self):
        chunks = list(iter_json_array([{"a": 1}, {"b": "c"}]))
        assert chunks == [b"[", b'{"a":1}', b",", b'{"b":"c"}', b"]"]
        assert json.loads(b"".join(chunks)) == [{"a": 1}, {"b": "c"}]

    def test_unicode_is_not_escaped(self):
        chunks = list(iter_json_array([{"path": "dati-\u010d"}]))
        assert b"\\u" not in b"".join(chunks)


class TestIterDirEntries:
    def test_lists_directories_with_permissions_in_walk_order(self, tmp_path):
        (tmp_path / "b").mkdir()
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "nested").mkdir()
        os.chmod(tmp_path / "a", 0o750)
        assert Dir.get(str(tmp_path / "a")) is not None

        entries = list(iter_dir_entries(str(tmp_path)))
        paths = [entry["path"] for entry in entries]

        # Deterministic per-directory walk order (same contract as the file
        # listing): siblings sorted, a tree not globally sorted.
        assert paths[0] == "a"
        assert set(paths) == {"a", "b", os.path.join("a", "nested")}
        by_path = {entry["path"]: entry["permissions"] for entry in entries}
        assert by_path["a"] == "750"

    def test_order_is_stable_across_calls(self, tmp_path):
        (tmp_path / "b").mkdir()
        (tmp_path / "a").mkdir()

        assert list(iter_dir_entries(str(tmp_path))) == list(iter_dir_entries(str(tmp_path)))

    def test_skips_dir_symlinks(self, tmp_path):
        (tmp_path / "real").mkdir()
        (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)

        paths = [entry["path"] for entry in iter_dir_entries(str(tmp_path))]

        assert "real" in paths
        assert "link" not in paths


class TestIterBucketEntries:
    def test_yields_files_and_safe_symlinks(self, tmp_path):
        _write(tmp_path / "a.txt", b"a")
        _write(tmp_path / "sub" / "b.txt", b"b")
        (tmp_path / "link.txt").symlink_to(tmp_path / "a.txt")

        entries = list(iter_bucket_entries(str(tmp_path)))
        by_name = {Path(path).name: link for path, link in entries}

        assert set(by_name) == {"a.txt", "b.txt", "link.txt"}
        assert by_name["a.txt"] is None
        assert by_name["link.txt"] is not None

    def test_skips_symlinks_escaping_the_bucket(self, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_bytes(b"top secret")
        bucket = tmp_path / "bucket"
        bucket.mkdir()
        (bucket / "leak").symlink_to(secret)

        entries = list(iter_bucket_entries(str(bucket)))

        assert entries == []

    def test_skips_engine_and_hidden_files(self, tmp_path):
        _write(tmp_path / ".hsyncignore", b"")
        _write(tmp_path / "keep.txt")
        (tmp_path / "partial.part").write_bytes(b"x")

        names = {Path(path).name for path, _ in iter_bucket_entries(str(tmp_path))}

        assert names == {"keep.txt"}

    def test_skip_suffixes_drops_matching_names(self, tmp_path):
        _write(tmp_path / "keep.txt")
        _write(tmp_path / "keep.txt.hsyncbak")

        names = {
            Path(path).name
            for path, _ in iter_bucket_entries(str(tmp_path), skip_suffixes=(".hsyncbak",))
        }

        assert names == {"keep.txt"}

    def test_start_dir_scans_a_subdirectory_only(self, tmp_path):
        _write(tmp_path / "top.txt")
        _write(tmp_path / "sub" / "inner.txt")

        names = {
            Path(path).name
            for path, _ in iter_bucket_entries(str(tmp_path), start_dir=str(tmp_path / "sub"))
        }

        assert names == {"inner.txt"}

    def test_dir_symlinks_only_when_requested(self, tmp_path):
        (tmp_path / "real").mkdir()
        _write(tmp_path / "real" / "f.txt")
        (tmp_path / "dirlink").symlink_to(tmp_path / "real", target_is_directory=True)

        default = list(iter_bucket_entries(str(tmp_path)))
        with_dirs = list(iter_bucket_entries(str(tmp_path), include_dir_symlinks=True))

        assert not any(Path(path).name == "dirlink" for path, _ in default)
        assert any(Path(path).name == "dirlink" for path, _ in with_dirs)


class TestEntryBuilders:
    def test_file_entry_uses_a_bucket_relative_path(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_bytes(b"abc")
        file_obj = File.get(str(target))
        assert file_obj is not None

        entry = file_entry(file_obj, str(tmp_path))

        assert entry["filepath"] == "a.txt"
        assert entry["size"] == 3
        assert entry["sha256sum"] == file_obj.sha256sum

    def test_symlink_entry_rejects_an_escaping_target(self, tmp_path):
        bucket = tmp_path / "bucket"
        bucket.mkdir()
        link = bucket / "leak"
        link.symlink_to(tmp_path / "outside")
        stored = Symlink.get(str(link))
        assert stored is not None

        assert symlink_entry(stored, str(link), str(bucket)) is None

    def test_symlink_entry_keeps_a_safe_target(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_bytes(b"a")
        link = tmp_path / "link"
        link.symlink_to(target)
        stored = Symlink.get(str(link))
        assert stored is not None

        entry = symlink_entry(stored, str(link), str(tmp_path))

        assert entry is not None
        assert entry["filepath"] == "link"
