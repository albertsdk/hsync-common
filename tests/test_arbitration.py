# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Unit tests for the shared causal upload arbitration."""

from __future__ import annotations

from hsync_common.models.arbitration import (
    ArbitrationOutcome,
    conflicted_copy_name,
    decide_arbitration,
    plan_self_record,
)
from hsync_common.models.version import FileVersion

CID_A = "TestClientA1234567890"
CID_B = "TestClientB1234567890"


def _stored(
    base_hash: str,
    vclock: dict[str, int],
    *,
    origin_cid: str | None = CID_B,
    corrected_mtime: int = 0,
) -> FileVersion:
    return FileVersion(
        base_hash=base_hash,
        version_id="v1",
        origin_cid=origin_cid,
        ts=1,
        vclock=vclock,
        corrected_mtime=corrected_mtime,
    )


def _decide(stored: FileVersion | None, *, incoming_hash: str, vclock: dict[str, int], **kwargs):
    return decide_arbitration(
        stored=stored,
        incoming_hash=incoming_hash,
        incoming_vclock_raw=vclock,
        incoming_version_id="v-in",
        incoming_origin_cid=kwargs.pop("origin_cid", CID_A),
        incoming_corrected_mtime=kwargs.pop("corrected_mtime", 0),
    )


class TestDecideArbitration:
    def test_no_stored_version_is_accepted(self):
        result = _decide(None, incoming_hash="h-in", vclock={CID_A: 1})
        assert result.outcome is ArbitrationOutcome.accepted
        assert result.record_vclock == {CID_A: 1}

    def test_identical_content_is_a_noop_accept(self):
        result = _decide(_stored("h", {CID_B: 1}), incoming_hash="h", vclock={CID_A: 1})
        assert result.outcome is ArbitrationOutcome.accepted
        assert result.record_vclock == {CID_A: 1, CID_B: 1}

    def test_dominated_incoming_is_superseded(self):
        result = _decide(
            _stored("h-stored", {CID_A: 1, CID_B: 2}),
            incoming_hash="h-in",
            vclock={CID_A: 1},
        )
        assert result.outcome is ArbitrationOutcome.superseded
        assert result.record_vclock == {CID_A: 1, CID_B: 2}

    def test_concurrent_newer_incoming_wins(self):
        result = _decide(
            _stored("h-stored", {CID_B: 1}, corrected_mtime=100),
            incoming_hash="h-in",
            vclock={CID_A: 1},
            corrected_mtime=200,
        )
        assert result.outcome is ArbitrationOutcome.accepted_conflict_won
        assert result.record_corrected_mtime == 200
        assert result.loser_cid == CID_B

    def test_concurrent_newer_stored_wins(self):
        result = _decide(
            _stored("h-stored", {CID_B: 1}, corrected_mtime=200),
            incoming_hash="h-in",
            vclock={CID_A: 1},
            corrected_mtime=100,
        )
        assert result.outcome is ArbitrationOutcome.conflict_lost
        assert result.record_corrected_mtime == 200
        assert result.loser_cid == CID_A

    def test_malformed_vclock_degrades_to_empty_clock(self):
        result = _decide(None, incoming_hash="h-in", vclock={"not-a-cid": 1})
        assert result.record_vclock == {}


class TestPlanSelfRecord:
    def test_drifted_disk_is_recorded_under_the_local_cid(self):
        advance = plan_self_record(_stored("h-stored", {CID_B: 1}), "h-disk", CID_A)
        assert advance is not None
        assert advance.base_hash == "h-disk"
        assert advance.vclock == {CID_B: 1, CID_A: 1}

    def test_no_advance_needed_when_disk_matches_the_base(self):
        assert plan_self_record(_stored("h", {CID_B: 1}), "h", CID_A) is None

    def test_no_advance_without_a_stored_version_or_disk_hash(self):
        assert plan_self_record(None, "h", CID_A) is None
        assert plan_self_record(_stored("h", {CID_B: 1}), None, CID_A) is None

    def test_no_advance_without_a_cid(self):
        assert plan_self_record(_stored("h-stored", {CID_B: 1}), "h-disk", None) is None


class TestConflictedCopyName:
    def test_uses_the_canonical_shape(self):
        name = conflicted_copy_name("/b/photo.jpg", CID_A, "20250101")
        assert name == f"/b/photo_conflicted_copy_20250101_{CID_A}.jpg"

    def test_sanitizes_and_bounds_the_cid(self):
        name = conflicted_copy_name("/b/f.txt", "a/../b " + "x" * 40, "ts")
        assert name == "/b/f_conflicted_copy_ts_a..b" + "x" * 28 + ".txt"

    def test_unknown_cid_falls_back(self):
        assert conflicted_copy_name("/b/f.txt", None, "ts") == "/b/f_conflicted_copy_ts_unknown.txt"
