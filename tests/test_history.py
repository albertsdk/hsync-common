# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Contract of the server-history record and its on-disk layout (ADR-0057).

The store is the server's counterpart of the sync trash: same payload shape, a
distinct entity (an overwrite is not a deletion). The rules are pinned here
because a damaged record must be skipped, never trusted, and no crafted path may
reach outside an entry.
"""

from __future__ import annotations

import pytest

from hsync_common.constants import (
    HISTORY_DIRNAME,
    HISTORY_PAYLOAD_DIRNAME,
    HISTORY_REASON_DELETE,
    HISTORY_REASON_OVERWRITE,
)
from hsync_common.models.history import (
    HISTORY_REASONS,
    history_bucket_dir,
    history_entry_dir,
    history_entry_payload_path,
    history_root,
    parse_history_entry,
)
from hsync_common.state_paths import state_path

_SHA = "a" * 64
_ENTRY_ID = "1700000000-deadbeef"


def _record(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "relpath": "docs/report.txt",
        "sha256": _SHA,
        "size": 1234,
        "mtime_ns": 1_700_000_000_000_000_000,
        "mode": 0o644,
        "recorded_at": 1_700_000_000,
        "reason": HISTORY_REASON_OVERWRITE,
        "cid": "abcdefghijklmnopqrstu",
        "bucket": "photos",
    }
    payload.update(overrides)
    return payload


class TestLayout:
    def test_the_root_defaults_under_the_state_dir(self) -> None:
        assert history_root() == state_path(HISTORY_DIRNAME)

    def test_an_explicit_root_wins(self, tmp_path) -> None:
        assert history_root(tmp_path / "custom") == tmp_path / "custom"

    def test_a_bucket_dir_uses_the_bucket_name(self, tmp_path) -> None:
        assert history_bucket_dir(tmp_path, "photos") == tmp_path / "photos"

    @pytest.mark.parametrize("bucket", ["", "..", "/abs", "a/b", "x" * 65])
    def test_an_unsafe_bucket_is_refused(self, tmp_path, bucket: str) -> None:
        with pytest.raises(ValueError):
            history_bucket_dir(tmp_path, bucket)

    def test_an_entry_dir_needs_an_id_this_store_mints(self, tmp_path) -> None:
        assert history_entry_dir(tmp_path, "photos", _ENTRY_ID) == (tmp_path / "photos" / _ENTRY_ID)
        for bad in ("", "..", "1700000000", "1700000000-XYZ", f"{_ENTRY_ID}/x"):
            with pytest.raises(ValueError):
                history_entry_dir(tmp_path, "photos", bad)

    def test_a_payload_path_is_contained(self, tmp_path) -> None:
        entry = tmp_path / _ENTRY_ID

        assert history_entry_payload_path(entry, "a/b.txt") == (
            entry / HISTORY_PAYLOAD_DIRNAME / "a" / "b.txt"
        )

    @pytest.mark.parametrize("relpath", ["", "/abs", "../x", "a/../../b", "a\\b", "./a", "a/"])
    def test_an_unsafe_payload_path_is_refused(self, tmp_path, relpath: str) -> None:
        with pytest.raises(ValueError):
            history_entry_payload_path(tmp_path / _ENTRY_ID, relpath)


class TestParsing:
    def test_a_complete_record_round_trips(self) -> None:
        entry = parse_history_entry(_record())

        assert entry is not None
        assert entry["relpath"] == "docs/report.txt"
        assert entry["reason"] == HISTORY_REASON_OVERWRITE
        assert entry["bucket"] == "photos"

    def test_every_minted_reason_is_accepted(self) -> None:
        for reason in HISTORY_REASONS:
            entry = parse_history_entry(_record(reason=reason))
            assert entry is not None
            assert entry["reason"] == reason

    @pytest.mark.parametrize("reason", ["", "sync", "user", "delete-all"])
    def test_an_unknown_reason_is_refused(self, reason: str) -> None:
        assert parse_history_entry(_record(reason=reason)) is None

    @pytest.mark.parametrize("field", ["relpath", "sha256", "size", "recorded_at"])
    def test_a_record_missing_a_required_field_is_refused(self, field: str) -> None:
        payload = _record()
        payload.pop(field)

        assert parse_history_entry(payload) is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"size": -1},
            {"size": True},
            {"recorded_at": 0},
            {"sha256": "not-a-hash"},
            {"relpath": "../escape"},
        ],
    )
    def test_a_malformed_record_is_refused(self, overrides: dict[str, object]) -> None:
        assert parse_history_entry(_record(**overrides)) is None

    def test_the_optional_fields_degrade(self) -> None:
        payload = _record()
        payload.pop("mtime_ns")
        payload.pop("mode")
        payload["cid"] = ""

        entry = parse_history_entry(payload)

        assert entry is not None
        assert entry["mtime_ns"] == 0
        assert entry["mode"] == 0
        assert entry["cid"] is None

    def test_a_non_mapping_is_refused(self) -> None:
        assert parse_history_entry(None) is None
        assert parse_history_entry([1, 2]) is None

    def test_the_delete_reason_is_a_distinct_value(self) -> None:
        """An overwrite and a deletion share the store but not the meaning."""
        assert HISTORY_REASON_DELETE != HISTORY_REASON_OVERWRITE
        entry = parse_history_entry(_record(reason=HISTORY_REASON_DELETE))
        assert entry is not None and entry["reason"] == HISTORY_REASON_DELETE
