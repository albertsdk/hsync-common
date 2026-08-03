"""Tests for hsync_common.models.version (causal vector-clock model, ADR-0022)."""

from hsync_common.models.version import (
    FileVersion,
    SyncDecision,
    SyncStateStore,
    VClockOrder,
    VersionInfo,
    compare_vclocks,
    merge_vclocks,
    new_version_id,
    parse_version_info,
    resolve_three_way,
    tick_vclock,
)

# Well-formed 21-char cids used across scenarios (is_valid_cid-compliant).
CID_A = "TestClientA1234567890"
CID_B = "TestClientB1234567890"
CID_C = "TestClientC1234567890"
CID_S = "TestClientX1234567890"  # server/seed node


class TestNewVersionId:
    def test_is_hex_string(self):
        vid = new_version_id()
        assert isinstance(vid, str)
        int(vid, 16)  # raises if not hex

    def test_is_unique(self):
        assert new_version_id() != new_version_id()


class TestCompareVclocks:
    def test_equal(self):
        assert compare_vclocks({CID_A: 3}, {CID_A: 3}) is VClockOrder.equal

    def test_dominates(self):
        assert compare_vclocks({CID_A: 3, CID_B: 2}, {CID_A: 3}) is VClockOrder.dominates

    def test_dominated(self):
        assert compare_vclocks({CID_A: 3}, {CID_A: 3, CID_B: 2}) is VClockOrder.dominated

    def test_concurrent(self):
        assert compare_vclocks({CID_A: 2}, {CID_B: 2}) is VClockOrder.concurrent

    def test_none_treated_as_empty(self):
        assert compare_vclocks(None, None) is VClockOrder.equal
        assert compare_vclocks({CID_A: 1}, None) is VClockOrder.dominates
        assert compare_vclocks(None, {CID_A: 1}) is VClockOrder.dominated

    def test_empty_dict_equals_none(self):
        assert compare_vclocks({}, None) is VClockOrder.equal


class TestTickVclock:
    def test_increments_own_counter(self):
        assert tick_vclock({CID_A: 3}, CID_A) == {CID_A: 4}

    def test_seeds_absent_author(self):
        assert tick_vclock(None, CID_A) == {CID_A: 1}

    def test_preserves_foreign_keys(self):
        result = tick_vclock({CID_A: 3, CID_B: 2}, CID_A)
        assert result == {CID_A: 4, CID_B: 2}

    def test_does_not_mutate_input(self):
        original = {CID_A: 3}
        tick_vclock(original, CID_A)
        assert original == {CID_A: 3}

    def test_monotonic_across_two_edits(self):
        c1 = tick_vclock({CID_A: 3}, CID_A)
        c2 = tick_vclock(c1, CID_A)
        assert compare_vclocks(c2, c1) is VClockOrder.dominates


class TestMergeVclocks:
    def test_componentwise_max(self):
        assert merge_vclocks({CID_A: 3, CID_B: 1}, {CID_A: 1, CID_C: 5}) == {
            CID_A: 3,
            CID_B: 1,
            CID_C: 5,
        }

    def test_none_operands(self):
        assert merge_vclocks(None, {CID_A: 1}) == {CID_A: 1}
        assert merge_vclocks(None, None) == {}


class TestParseVersionInfo:
    def test_well_formed(self):
        info = parse_version_info(
            {"vclock": {CID_A: 3}, "version_id": "vid", "origin_cid": CID_A, "ts": 7}
        )
        assert info is not None
        assert info["vclock"] == {CID_A: 3}
        assert info["version_id"] == "vid"
        assert info["origin_cid"] == CID_A
        assert info["ts"] == 7

    def test_non_dict_returns_none(self):
        assert parse_version_info("nope") is None
        assert parse_version_info(None) is None

    def test_vclock_not_dict_returns_none(self):
        assert parse_version_info({"vclock": [1, 2]}) is None

    def test_invalid_cid_key_returns_none(self):
        assert parse_version_info({"vclock": {"bad-key!": 1}}) is None

    def test_bool_value_rejected(self):
        # bool is a subclass of int; it must not silently parse as 1.
        assert parse_version_info({"vclock": {CID_A: True}}) is None

    def test_negative_value_rejected(self):
        assert parse_version_info({"vclock": {CID_A: -1}}) is None

    def test_invalid_origin_cid_returns_none(self):
        assert parse_version_info({"vclock": {}, "origin_cid": "not-a-cid"}) is None

    def test_missing_version_id_defaults_to_empty(self):
        info = parse_version_info({"vclock": {}, "ts": 0})
        assert info is not None
        assert info["version_id"] == ""

    def test_oversize_vclock_rejected(self):
        huge = {f"TestClientX1234567890{i:02d}": 1 for i in range(300)}
        # All keys are valid 21-char cids but there are too many entries.
        assert parse_version_info({"vclock": huge, "ts": 0}) is None

    def test_malformed_ts_returns_none(self):
        assert parse_version_info({"vclock": {}, "ts": "abc"}) is None

    def test_corrected_mtime_parsed(self):
        info = parse_version_info(
            {"vclock": {}, "version_id": "v", "origin_cid": CID_A, "ts": 7, "corrected_mtime": 1234}
        )
        assert info is not None and info["corrected_mtime"] == 1234

    def test_corrected_mtime_defaults_to_zero(self):
        # Older payloads without the field parse fine with unknown ≃ 0 (the
        # hash fallback applies natively when either side has it unset).
        info = parse_version_info({"vclock": {}, "version_id": "v", "ts": 7})
        assert info is not None and info["corrected_mtime"] == 0

    def test_malformed_corrected_mtime_tolerated(self):
        # A malformed chronological field degrades to the hash fallback, never
        # to a protocol error.
        for bad in ("abc", None, [1]):
            info = parse_version_info({"vclock": {}, "ts": 7, "corrected_mtime": bad})
            assert info is not None and info["corrected_mtime"] == 0

    def test_bool_corrected_mtime_rejected_as_unknown(self):
        info = parse_version_info({"vclock": {}, "ts": 7, "corrected_mtime": True})
        assert info is not None and info["corrected_mtime"] == 0


class TestResolveThreeWay:
    """The causal decision matrix (§3.2 of ADR-0022)."""

    def test_identical_content_is_in_sync(self):
        assert resolve_three_way("h", {CID_A: 1}, "h", {CID_A: 1}, "h") is SyncDecision.in_sync
        assert resolve_three_way("h", None, "h", None, None) is SyncDecision.in_sync

    # ── base-hash fast paths (content identity, clock-independent) ──────────
    def test_local_at_base_downloads(self):
        assert resolve_three_way("base", {CID_A: 1}, "remote", {CID_A: 2}, "base") is (
            SyncDecision.download
        )

    def test_remote_at_base_uploads(self):
        assert resolve_three_way("local", {CID_A: 2}, "base", {CID_A: 1}, "base") is (
            SyncDecision.upload
        )

    # ── vector-clock dominance ──────────────────────────────────────────────
    def test_remote_dominates_downloads(self):
        assert resolve_three_way("h1", {CID_A: 1}, "h2", {CID_A: 2}, "h0") is (
            SyncDecision.download
        )

    def test_local_dominates_uploads(self):
        assert resolve_three_way("h2", {CID_A: 2}, "h1", {CID_A: 1}, "h0") is (SyncDecision.upload)

    # ── true divergence (concurrent) → deterministic tie-break ──────────────
    def test_concurrent_local_wins_tie_break_uploads(self):
        # Both changed since base, clocks concurrent; higher hash wins.
        assert resolve_three_way("zzz", {CID_A: 2}, "aaa", {CID_B: 2}, "base") is (
            SyncDecision.conflict_upload
        )

    def test_concurrent_remote_wins_tie_break_downloads(self):
        assert resolve_three_way("aaa", {CID_A: 2}, "zzz", {CID_B: 2}, "base") is (
            SyncDecision.conflict_download
        )

    def test_concurrent_equal_hashes_impossible_in_sync(self):
        # Equal hashes would have hit rule 1 (in_sync) before reaching tie-break.
        assert resolve_three_way("h", {CID_A: 1}, "h", {CID_B: 1}, "base") is (SyncDecision.in_sync)

    # ── corrected-mtime tie-break on true divergence (ADR-0023) ─────────────
    def test_corrected_mtime_local_newer_wins(self):
        # The raw wall clock is never read by the matrix: the decision comes
        # exclusively from the corrected values supplied by the callers, even
        # when the hash order would point the other way ("aaa" vs "zzz").
        assert (
            resolve_three_way(
                "aaa",
                {CID_A: 2},
                "zzz",
                {CID_B: 2},
                "base",
                local_corrected_mtime=200,
                remote_corrected_mtime=100,
            )
            is SyncDecision.conflict_upload
        )

    def test_corrected_mtime_remote_newer_wins(self):
        assert (
            resolve_three_way(
                "zzz",
                {CID_A: 2},
                "aaa",
                {CID_B: 2},
                "base",
                local_corrected_mtime=100,
                remote_corrected_mtime=200,
            )
            is SyncDecision.conflict_download
        )

    def test_equal_corrected_mtimes_fall_back_to_hash(self):
        assert (
            resolve_three_way(
                "zzz",
                {CID_A: 2},
                "aaa",
                {CID_B: 2},
                "base",
                local_corrected_mtime=150,
                remote_corrected_mtime=150,
            )
            is SyncDecision.conflict_upload
        )
        assert (
            resolve_three_way(
                "aaa",
                {CID_A: 2},
                "zzz",
                {CID_B: 2},
                "base",
                local_corrected_mtime=150,
                remote_corrected_mtime=150,
            )
            is SyncDecision.conflict_download
        )

    def test_missing_corrected_mtime_falls_back_to_hash(self):
        # A side without the field (0 = unknown) triggers the deterministic
        # hash fallback so every peer still converges.
        assert (
            resolve_three_way(
                "zzz",
                {CID_A: 2},
                "aaa",
                {CID_B: 2},
                "base",
                local_corrected_mtime=100,
                remote_corrected_mtime=0,
            )
            is SyncDecision.conflict_upload
        )
        assert (
            resolve_three_way(
                "aaa",
                {CID_A: 2},
                "zzz",
                {CID_B: 2},
                "base",
                local_corrected_mtime=0,
                remote_corrected_mtime=100,
            )
            is SyncDecision.conflict_download
        )

    def test_corrected_mtime_never_overrides_causality(self):
        # Dominance wins regardless of which corrected mtime is newer: the
        # chronological tie-break only applies to true divergence.
        assert (
            resolve_three_way(
                "h1",
                {CID_A: 1},
                "h2",
                {CID_A: 2},
                "h0",
                local_corrected_mtime=999,
                remote_corrected_mtime=1,
            )
            is SyncDecision.download
        )
        assert (
            resolve_three_way(
                "h2",
                {CID_A: 2},
                "h1",
                {CID_A: 1},
                "h0",
                local_corrected_mtime=1,
                remote_corrected_mtime=999,
            )
            is SyncDecision.upload
        )

    # ── unknown base, no clocks (replaces the old unknown_base legacy tie) ──
    def test_no_base_no_clocks_different_content_is_concurrent_tie_break(self):
        # First-ever contact with differing content: concurrent ⇒ tie-break,
        # never a legacy mtime fallback.
        assert resolve_three_way("zzz", None, "aaa", None, None) is (SyncDecision.conflict_upload)
        assert resolve_three_way("aaa", None, "zzz", None, None) is (SyncDecision.conflict_download)

    def test_no_base_remote_has_clock_remote_dominates(self):
        # Remote has causal history, local has none (empty clock) ⇒ dominated.
        assert resolve_three_way("h1", None, "h2", {CID_B: 1}, None) is (SyncDecision.download)

    def test_no_base_local_has_clock_local_dominates(self):
        assert resolve_three_way("h2", {CID_A: 1}, "h1", None, None) is SyncDecision.upload

    # ── equal-clock anomaly (defensive: treated as concurrent) ──────────────
    def test_equal_clocks_different_hashes_concurrent(self):
        assert resolve_three_way("zzz", {CID_A: 1}, "aaa", {CID_A: 1}, "base") is (
            SyncDecision.conflict_upload
        )

    # ── relay scenario (core motivation: no false conflict via relay) ───────
    def test_relayed_version_dominates_no_false_conflict(self):
        # C holds the base {S:3}; A's edit {S:3,A:1} relays to C via B.
        # C compares its {S:3} against the relayed {S:3,A:1} ⇒ dominated ⇒
        # download, NOT a conflict.
        assert (
            resolve_three_way(
                "h0",
                {CID_S: 3},
                "h1",
                {CID_S: 3, CID_A: 1},
                "h0",
            )
            is SyncDecision.download
        )

    # ── absent-file (deletion) cases flow through hash logic ────────────────
    def test_both_absent_is_in_sync(self):
        assert resolve_three_way(None, None, None, None, "base") is SyncDecision.in_sync

    def test_local_deleted_remote_unchanged_uploads(self):
        assert resolve_three_way(None, None, "base", {CID_A: 1}, "base") is (SyncDecision.upload)

    def test_remote_deleted_local_unchanged_downloads(self):
        assert resolve_three_way("base", {CID_A: 1}, None, None, "base") is (SyncDecision.download)


class TestSyncStateStoreMutation:
    def test_record_and_get(self):
        store = SyncStateStore()
        store.record(
            "a/b.txt",
            base_hash="hh",
            version_id="vid",
            origin_cid=CID_A,
            timestamp=42,
            vclock={CID_A: 3},
        )
        entry = store.get("a/b.txt")
        assert entry is not None
        assert entry["base_hash"] == "hh"
        assert entry["version_id"] == "vid"
        assert entry["origin_cid"] == CID_A
        assert entry["ts"] == 42
        assert entry["vclock"] == {CID_A: 3}

    def test_record_defaults_version_id_ts_and_empty_vclock(self):
        store = SyncStateStore()
        store.record("x.txt", base_hash="hh")
        entry = store.get("x.txt")
        assert entry is not None
        assert entry["version_id"]  # auto-minted, non-empty
        assert entry["origin_cid"] is None
        assert entry["ts"] > 0
        assert entry["vclock"] == {}

    def test_base_hash_helper(self):
        store = SyncStateStore()
        store.record("x.txt", base_hash="hh")
        assert store.base_hash("x.txt") == "hh"
        assert store.base_hash("missing.txt") is None

    def test_record_overwrites(self):
        store = SyncStateStore()
        store.record("x.txt", base_hash="old", vclock={CID_A: 1})
        store.record("x.txt", base_hash="new", vclock={CID_A: 2})
        assert store.base_hash("x.txt") == "new"
        assert store.get("x.txt")["vclock"] == {CID_A: 2}
        assert len(store) == 1

    def test_clear(self):
        store = SyncStateStore()
        store.record("x.txt", base_hash="hh")
        assert store.clear("x.txt") is True
        assert store.clear("x.txt") is False
        assert store.get("x.txt") is None

    def test_retain_drops_stale(self):
        store = SyncStateStore()
        store.record("keep.txt", base_hash="h1")
        store.record("drop.txt", base_hash="h2")
        dropped = store.retain(["keep.txt"])
        assert dropped == 1
        assert store.base_hash("keep.txt") == "h1"
        assert store.get("drop.txt") is None


class TestSyncStateStorePersistence:
    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "sub" / ".hsyncstate")
        store = SyncStateStore(path=path)
        store.record(
            "a/b.txt",
            base_hash="hh",
            version_id="vid",
            origin_cid=CID_A,
            timestamp=7,
            vclock={CID_A: 3, CID_B: 1},
        )
        store.save()

        reloaded = SyncStateStore(path=path)
        reloaded.load()
        entry = reloaded.get("a/b.txt")
        assert entry is not None
        assert entry["base_hash"] == "hh"
        assert entry["version_id"] == "vid"
        assert entry["origin_cid"] == CID_A
        assert entry["ts"] == 7
        assert entry["vclock"] == {CID_A: 3, CID_B: 1}

    def test_load_missing_file_is_noop(self, tmp_path):
        store = SyncStateStore(path=str(tmp_path / "absent.json"))
        store.load()
        assert len(store) == 0

    def test_load_corrupt_file_is_noop(self, tmp_path):
        path = tmp_path / ".hsyncstate"
        path.write_text("{not json", encoding="utf-8")
        store = SyncStateStore(path=str(path))
        store.load()
        assert len(store) == 0

    def test_save_without_path_is_noop(self):
        store = SyncStateStore()
        store.record("x.txt", base_hash="hh")
        store.save()  # must not raise

    def test_load_drops_entries_without_vclock(self, tmp_path):
        # The conflict model is strictly causal (ADR-0003): an entry without a
        # valid clock carries no causal history and is dropped, never loaded
        # with a fabricated empty clock that could flip a sync decision.
        import json

        path = tmp_path / ".hsyncstate"
        path.write_text(
            json.dumps(
                {
                    "versions": {
                        "novclock": {
                            "base_hash": "h",
                            "version_id": "v",
                            "origin_cid": None,
                            "ts": 7,
                        },
                        "ok": {
                            "base_hash": "h",
                            "version_id": "v",
                            "origin_cid": None,
                            "ts": 7,
                            "vclock": {},
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        store = SyncStateStore(path=str(path))
        store.load()
        entries = store.iter_entries()
        assert len(entries) == 1
        _, entry = entries[0]
        assert entry["base_hash"] == "h"
        assert entry["vclock"] == {}

    def test_load_skips_entries_without_base_hash(self, tmp_path):
        import json

        path = tmp_path / ".hsyncstate"
        path.write_text(
            json.dumps(
                {
                    "versions": {
                        "k1": {"version_id": "v"},
                        "k2": {"base_hash": "h", "ts": 7, "vclock": {CID_A: 1}},
                    }
                }
            ),
            encoding="utf-8",
        )
        store = SyncStateStore(path=str(path))
        store.load()
        assert len(store) == 1

    def test_load_skips_entries_with_malformed_ts(self, tmp_path):
        import json

        path = tmp_path / ".hsyncstate"
        path.write_text(
            json.dumps(
                {
                    "versions": {
                        "ok": {
                            "base_hash": "h",
                            "version_id": "v",
                            "origin_cid": None,
                            "ts": 7,
                            "vclock": {},
                        },
                        "bad-ts": {"base_hash": "h", "ts": "abc", "vclock": {}},
                        "null-ts": {"base_hash": "h", "ts": None, "vclock": {}},
                        "bool-ts": {"base_hash": "h", "ts": True, "vclock": {}},
                    }
                }
            ),
            encoding="utf-8",
        )
        store = SyncStateStore(path=str(path))
        store.load()
        assert len(store) == 1

    def test_load_drops_malformed_vclock_entries(self, tmp_path):
        # A hand-edited side-car with a structurally invalid vclock makes the
        # entry unusable: it is dropped whole rather than loaded with an
        # empty clock, which could mask a corrupted common ancestor.
        import json

        path = tmp_path / ".hsyncstate"
        path.write_text(
            json.dumps(
                {
                    "versions": {
                        "ok": {"base_hash": "h", "ts": 7, "vclock": {CID_A: 1}},
                        "bad-value": {"base_hash": "h", "ts": 7, "vclock": {"x": "not-int"}},
                        "neg-counter": {"base_hash": "h", "ts": 7, "vclock": {CID_A: -1}},
                        "non-dict": {"base_hash": "h", "ts": 7, "vclock": [1, 2]},
                    }
                }
            ),
            encoding="utf-8",
        )
        store = SyncStateStore(path=str(path))
        store.load()
        assert len(store) == 1
        _, ok = store.iter_entries()[0]
        assert ok["vclock"] == {CID_A: 1}

    def test_load_malformed_versions_member_is_noop(self, tmp_path):
        import json

        path = tmp_path / ".hsyncstate"
        path.write_text(json.dumps({"versions": ["not", "a", "dict"]}), encoding="utf-8")
        store = SyncStateStore(path=str(path))
        store.load()
        assert len(store) == 0

    def test_load_skips_non_dict_entries(self, tmp_path):
        import json

        path = tmp_path / ".hsyncstate"
        path.write_text(
            json.dumps(
                {
                    "versions": {
                        "ok": {"base_hash": "h", "ts": 7, "vclock": {}},
                        "junk": "not-a-dict",
                    }
                }
            ),
            encoding="utf-8",
        )
        store = SyncStateStore(path=str(path))
        store.load()
        assert len(store) == 1


class TestFileVersionTypedDict:
    def test_construct(self):
        v: FileVersion = {
            "base_hash": "h",
            "version_id": "v",
            "origin_cid": None,
            "ts": 1,
            "vclock": {},
            "corrected_mtime": 0,
        }
        assert v["base_hash"] == "h"
        assert v["corrected_mtime"] == 0

    def test_version_info_construct(self):
        vi: VersionInfo = {
            "vclock": {CID_A: 1},
            "version_id": "v",
            "origin_cid": CID_A,
            "ts": 1,
            "corrected_mtime": 0,
        }
        assert vi["vclock"] == {CID_A: 1}
