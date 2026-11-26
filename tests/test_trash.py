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

from hsync_common.constants import (
    TRASH_ENTRY_FILENAME,
    TRASH_PAYLOAD_DIRNAME,
    TRASH_RESTORING_SUFFIX,
)
from hsync_common.models.trash import (
    TRASH_ORIGIN_SYNC,
    TRASH_ORIGIN_USER,
    TRASH_RESTORE_ALL_STATUSES,
    TRASH_RESTORE_STATUSES,
    TRASH_SWEEP_INTERVAL_SECONDS,
    TRASH_UNRECOVERABLE_RESTORE,
    TREE_TRASH_MAX_BYTES,
    TREE_TRASH_MAX_FILES,
    TrashEntry,
    TrashSweepEntry,
    build_trash_contract,
    entry_dir,
    entry_payload_path,
    is_safe_folder_id,
    is_safe_relpath,
    parse_trash_entry,
    plan_trash_sweep,
    trash_folder_dir,
    trash_root,
    trash_root_inside_folder,
)
from hsync_common.protocol.fixtures import build_fixtures

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


class TestTrashRootInsideFolder:
    """The store is device-local, so it must never sit in the shared tree."""

    def test_the_folder_itself_is_refused(self, tmp_path):
        assert trash_root_inside_folder(tmp_path, tmp_path) is True

    def test_a_subdirectory_of_the_folder_is_refused(self, tmp_path):
        assert trash_root_inside_folder(tmp_path / "shared" / ".trash", tmp_path / "shared") is True

    def test_a_sibling_directory_is_accepted(self, tmp_path):
        assert trash_root_inside_folder(tmp_path / "trash", tmp_path / "shared") is False

    def test_a_parent_directory_is_accepted(self, tmp_path):
        """A store above the folder keeps its bytes on the device (the state dir)."""
        assert trash_root_inside_folder(tmp_path, tmp_path / "shared") is False

    def test_the_comparison_survives_a_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert trash_root_inside_folder("shared/.trash", "shared") is True


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
            {"origin": ""},
            {"origin": 5},
        ],
    )
    def test_damaged_records_are_skipped(self, overrides):
        assert parse_trash_entry(_entry(**overrides)) is None

    def test_an_absent_origin_is_the_sync_origin(self):
        payload = _entry()
        payload.pop("origin")

        entry = parse_trash_entry(payload)

        assert entry is not None
        assert entry["origin"] == TRASH_ORIGIN_SYNC

    @pytest.mark.parametrize("payload", [None, [], "text", 7])
    def test_non_mapping_payloads_are_skipped(self, payload):
        assert parse_trash_entry(payload) is None


class TestContract:
    """The published ``trash-contract`` fixture and the values behind it."""

    def test_the_fixture_is_part_of_the_golden_set(self):
        assert "trash-contract" in build_fixtures()

    def test_the_unrecoverable_refusals_are_restore_statuses(self):
        assert TRASH_UNRECOVERABLE_RESTORE <= TRASH_RESTORE_STATUSES
        assert "restored" in TRASH_RESTORE_STATUSES
        assert {"ok", "disabled"} == TRASH_RESTORE_ALL_STATUSES

    def test_the_policy_bounds_are_positive(self):
        assert TREE_TRASH_MAX_FILES > 0
        assert TREE_TRASH_MAX_BYTES > 0
        assert TRASH_SWEEP_INTERVAL_SECONDS > 0

    def test_the_layout_names_are_the_written_ones(self):
        entry = build_trash_contract()["entry"]

        assert entry["filename"] == TRASH_ENTRY_FILENAME
        assert entry["payload_dirname"] == TRASH_PAYLOAD_DIRNAME
        assert entry["restoring_suffix"] == TRASH_RESTORING_SUFFIX
        assert entry["keys"] == sorted(TrashEntry.__annotations__)

    def test_every_record_case_carries_the_live_verdict(self):
        cases = build_trash_contract()["entry_cases"]

        assert any(case["accepted"] for case in cases)
        assert any(not case["accepted"] for case in cases)
        for case in cases:
            assert case["accepted"] is (parse_trash_entry(case["payload"]) is not None)

    def test_every_relpath_case_carries_the_live_verdict(self):
        cases = build_trash_contract()["relpath_cases"]

        assert any(case["safe"] for case in cases)
        assert any(not case["safe"] for case in cases)
        for case in cases:
            assert case["safe"] is is_safe_relpath(case["path"])


class TestSweepPlan:
    """The rule behind ``prune_store`` and the ``prune_cases`` of the contract."""

    _NOW = 1_700_000_000
    _DAY = 86_400

    def _plan(self, entries, *, retention_days=30, budget=10_000):
        return plan_trash_sweep(
            [TrashSweepEntry(*entry) for entry in entries],
            retention_days=retention_days,
            budget=budget,
            now=self._NOW,
        )

    def test_the_window_drops_only_what_is_older(self):
        plan = self._plan(
            [
                ("old", self._NOW - 40 * self._DAY, 10),
                ("edge", self._NOW - 30 * self._DAY, 20),
            ]
        )

        assert plan.expired == ("old",)
        assert plan.kept == 1
        assert plan.freed == 10

    def test_a_zero_window_keeps_everything(self):
        plan = self._plan([("old", self._NOW - 4_000 * self._DAY, 10)], retention_days=0)

        assert plan.expired == ()
        assert plan.kept == 1

    def test_eviction_is_oldest_first_and_budget_is_strict(self):
        plan = self._plan(
            [
                ("new", self._NOW - self._DAY, 60),
                ("old", self._NOW - 5 * self._DAY, 60),
            ],
            retention_days=0,
            budget=100,
        )
        exact = self._plan([("only", self._NOW, 100)], retention_days=0, budget=100)

        assert plan.evicted == ("old",)
        assert plan.kept == 1
        assert plan.freed == 60
        assert exact.evicted == ()

    def test_entries_of_one_second_are_ordered_by_id(self):
        plan = self._plan(
            [("b", self._NOW - self._DAY, 60), ("a", self._NOW - self._DAY, 60)],
            retention_days=0,
            budget=100,
        )

        assert plan.evicted == ("a",)

    def test_the_window_is_applied_before_the_budget(self):
        plan = self._plan(
            [
                ("old", self._NOW - 40 * self._DAY, 80),
                ("new", self._NOW - self._DAY, 60),
                ("newer", self._NOW, 50),
            ],
            budget=100,
        )

        assert plan.expired == ("old",)
        assert plan.evicted == ("new",)
        assert plan.kept == 1
        assert plan.freed == 140

    def test_the_published_cases_carry_the_live_plan(self):
        for case in build_trash_contract()["prune_cases"]:
            plan = plan_trash_sweep(
                [
                    TrashSweepEntry(entry["entry_id"], entry["deleted_at"], entry["size"])
                    for entry in case["entries"]
                ],
                retention_days=case["retention_days"],
                budget=case["budget"],
                now=case["now"],
            )

            assert sorted(plan.expired) == case["expired"]
            assert sorted(plan.evicted) == case["evicted"]
            assert plan.kept == case["kept"]
            assert plan.freed == case["freed"]
            assert case["discarded"] == len(case["broken"])
