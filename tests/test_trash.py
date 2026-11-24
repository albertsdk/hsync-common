# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Contract of the sync-trash record and its on-disk layout (ADR-0056).

The store is shared with every front-end through ``entry.json`` and the client's
JSON listing, so the validation rules are pinned here: an unsafe path or a
damaged record must be skipped, never trusted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hsync_common.constants import TRASH_PAYLOAD_DIRNAME
from hsync_common.models.trash import (
    TRASH_ORIGIN_SYNC,
    TRASH_ORIGIN_USER,
    entry_dir,
    entry_payload_path,
    is_safe_folder_id,
    is_safe_relpath,
    parse_trash_entry,
    trash_folder_dir,
    trash_root,
)

_ENTRY_ID = "1700000000-deadbeef"
_FOLDER_ID = "5f2a1c3e-1234-4abc-9def-0123456789ab"


def _entry(**overrides):
    payload = {
        "relpath": "docs/report.pdf",
        "sha256": "a" * 64,
        "size": 42,
        "mtime_ns": 1_700_000_000_000_000_000,
        "mode": 0o644,
        "deleted_at": 1_700_000_100,
        "origin": TRASH_ORIGIN_SYNC,
        "cid": "DeviceCid123456",
        "bucket": "team",
    }
    payload.update(overrides)
    return payload


class TestSafeRelpath:
    @pytest.mark.parametrize(
        "relpath",
        ["a.txt", "dir/sub/file.bin", "with space.txt", ".hidden/file"],
    )
    def test_accepts_bucket_relative_paths(self, relpath):
        assert is_safe_relpath(relpath) is True

    @pytest.mark.parametrize(
        "relpath",
        [
            "",
            "/etc/passwd",
            "\\windows\\system32",
            "C:/Windows",
            "../outside",
            "a/../../b",
            "a//b",
            "a/",
            "./a",
            "bad\x00name",
            "back\\slash",
            42,
        ],
    )
    def test_rejects_anything_that_could_escape(self, relpath):
        assert is_safe_relpath(relpath) is False


class TestIds:
    def test_folder_id_matches_the_marker_shape(self):
        assert is_safe_folder_id(_FOLDER_ID) is True

    @pytest.mark.parametrize("folder_id", ["", "..", "a/b", "a b", "x" * 80, None])
    def test_folder_id_refuses_separators_and_junk(self, folder_id):
        assert is_safe_folder_id(folder_id) is False


class TestLayout:
    def test_tree_is_folder_then_entry_then_payload(self, tmp_path):
        root = trash_root(tmp_path / "trash")
        entry = entry_dir(root, _FOLDER_ID, _ENTRY_ID)

        payload = entry_payload_path(entry, "docs/report.pdf")

        assert entry == root / _FOLDER_ID / _ENTRY_ID
        assert payload == entry / TRASH_PAYLOAD_DIRNAME / "docs" / "report.pdf"

    def test_unsafe_ids_are_refused(self, tmp_path):
        root = trash_root(tmp_path)
        with pytest.raises(ValueError):
            trash_folder_dir(root, "../escape")
        with pytest.raises(ValueError):
            entry_dir(root, _FOLDER_ID, "not-an-entry")

    def test_unsafe_payload_path_is_refused(self, tmp_path):
        entry = entry_dir(trash_root(tmp_path), _FOLDER_ID, _ENTRY_ID)
        with pytest.raises(ValueError):
            entry_payload_path(entry, "../escape.txt")


class TestTrashRoot:
    def test_explicit_directory_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HSYNC_TRASH_DIR", str(tmp_path / "env"))
        assert trash_root(tmp_path / "explicit") == tmp_path / "explicit"

    def test_environment_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HSYNC_TRASH_DIR", str(tmp_path / "env"))
        assert trash_root() == tmp_path / "env"

    def test_default_lives_under_the_state_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("HSYNC_TRASH_DIR", raising=False)
        monkeypatch.setenv("HSYNC_STATE_DIR", str(tmp_path / "state"))

        assert trash_root() == Path(tmp_path / "state" / "trash")


class TestParseEntry:
    def test_a_valid_record_round_trips(self):
        entry = parse_trash_entry(_entry())

        assert entry is not None
        assert entry["relpath"] == "docs/report.pdf"
        assert entry["size"] == 42
        assert entry["origin"] == TRASH_ORIGIN_SYNC

    def test_optional_fields_get_safe_defaults(self):
        payload = _entry()
        for key in ("mtime_ns", "mode", "cid", "bucket"):
            payload.pop(key)

        entry = parse_trash_entry(payload)

        assert entry is not None
        assert entry["mtime_ns"] == 0
        assert entry["mode"] == 0
        assert entry["cid"] is None
        assert entry["bucket"] == ""

    def test_the_user_origin_is_accepted(self):
        entry = parse_trash_entry(_entry(origin=TRASH_ORIGIN_USER))
        assert entry is not None
        assert entry["origin"] == TRASH_ORIGIN_USER

    @pytest.mark.parametrize(
        "overrides",
        [
            {"relpath": "../escape"},
            {"relpath": ""},
            {"sha256": "not-a-hash"},
            {"sha256": "A" * 64},
            {"size": -1},
            {"size": True},
            {"size": "42"},
            {"deleted_at": 0},
            {"origin": "somewhere-else"},
        ],
    )
    def test_damaged_records_are_skipped(self, overrides):
        assert parse_trash_entry(_entry(**overrides)) is None

    @pytest.mark.parametrize("payload", [None, [], "text", 7])
    def test_non_mapping_payloads_are_skipped(self, payload):
        assert parse_trash_entry(payload) is None
