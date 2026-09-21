"""Tests for hsync_common models (File, Dir, Symlink, Event, SyncAction)."""

import json
import time

from hsync_common.models.dir import Dir
from hsync_common.models.event import Event, EventName, is_valid_cid
from hsync_common.models.file import (
    File,
)
from hsync_common.models.sync_action import SyncAction, SyncActionName
from hsync_common.models.tombstone import (
    TombstoneStore,
    relpath_in_bucket,
    tombstone_key,
)

# Well-formed 21-char cids for causal tombstone tests (is_valid_cid-compliant).
_CID_A = "TestClientA1234567890"
_CID_B = "TestClientB1234567890"


def _tomb(sha: str | None, vclock: dict[str, int], ts: int) -> dict:
    """Build a wire-shaped causal tombstone payload entry for tests."""
    return {"ts": ts, "sha256": sha, "vclock": vclock, "version_id": "v1", "origin_cid": _CID_A}


# SyncAction model
# =============================================================================


class TestSyncActionName:
    def test_values(self):
        assert SyncActionName.download == "download"
        assert SyncActionName.upload == "upload"
        assert SyncActionName.delete == "delete"
        assert SyncActionName.nothing == "nothing"


class TestSyncAction:
    def test_format_zero_timedelta(self):
        f = File(filepath="/tmp/f.txt", size=0)
        sa = SyncAction(file=f, name=SyncActionName.nothing, timedelta=0)
        assert sa.timedelta == "0s"

    def test_format_complex_timedelta(self):
        f = File(filepath="/tmp/f.txt", size=0)
        sa = SyncAction(file=f, timedelta=3661)  # 1h 1m 1s
        assert "1h" in sa.timedelta
        assert "1m" in sa.timedelta
        assert "1s" in sa.timedelta

    def test_to_dict(self):
        f = File(filepath="/tmp/f.txt", size=0)
        sa = SyncAction(file=f, name=SyncActionName.upload, timedelta=10)
        d = sa.to_dict()
        assert "file" in d
        assert "name" in d
        assert d["name"] == SyncActionName.upload
        assert d["timedelta"] == "10s"
        assert d["conflict"] is False

    def test_to_dict_includes_conflict_flag(self):
        # The conflict signal must survive serialization: a consumer that
        # only sees the dict would otherwise overwrite the local copy.
        f = File(filepath="/tmp/f.txt", size=0)
        sa = SyncAction(file=f, name=SyncActionName.download, conflict=True)
        assert sa.to_dict()["conflict"] is True

    def test_format_timedelta_includes_days(self):
        f = File(filepath="/tmp/f.txt", size=0)
        sa = SyncAction(file=f, timedelta=90_061)  # 1d 1h 1m 1s
        assert "1d" in sa.timedelta

    def test_repr_contains_fields(self):
        f = File(filepath="/tmp/f.txt", size=0)
        sa = SyncAction(file=f, name=SyncActionName.delete, timedelta=5)
        text = repr(sa)
        assert "SyncAction(" in text
        assert "delete" in text


# =============================================================================
# Event model
# =============================================================================


class TestEventName:
    def test_all_values(self):
        assert EventName.added == "added"
        assert EventName.modified == "modified"
        assert EventName.renamed == "renamed"
        assert EventName.deleted == "deleted"
        assert EventName.symlink == "symlink"


class TestIsValidCid:
    """Wire-facing client-ID format validation."""

    def test_valid_cids(self):
        # Exactly 21 alphanumeric characters — the fixed wire-contract length.
        assert is_valid_cid("V1StGXR8Z5jdHi6BmyTab") is True
        assert is_valid_cid("a" * 21) is True
        assert is_valid_cid("0" * 21) is True

    def test_invalid_length(self):
        # Too short or too long — only exactly 21 characters is valid.
        assert is_valid_cid("abc123") is False  # 6 chars
        assert is_valid_cid("") is False
        assert is_valid_cid("a" * 20) is False
        assert is_valid_cid("a" * 22) is False
        assert is_valid_cid("a" * 64) is False
        assert is_valid_cid("a" * 65) is False

    def test_invalid_chars(self):
        # Only [A-Za-z0-9] is allowed — any other character is rejected.
        assert is_valid_cid("bad cid") is False
        assert is_valid_cid("bad/cid") is False
        assert is_valid_cid("bad.cid") is False
        assert is_valid_cid("abc-def") is False
        assert is_valid_cid("abc_def") is False

    def test_non_string_types(self):
        assert is_valid_cid(None) is False
        assert is_valid_cid(123) is False

    def test_non_alphanumeric_cids_rejected(self):
        # The wire contract is strictly alphanumeric: a cid must always start
        # with (and contain only) ASCII letters/digits — no `-`/`_` anywhere.
        assert is_valid_cid("_-zjbhgmW2hWfht39QoaZ") is False
        assert is_valid_cid("-abc") is False
        assert is_valid_cid("_abc") is False
        assert is_valid_cid("abc-def") is False
        assert is_valid_cid("abc_def") is False
        assert is_valid_cid("V1StGXR8_Z5jdHi6B-myT") is False

    def test_trailing_newline_rejected(self):
        # Python's `$` also matches before a final newline: with plain
        # `re.match` a cid like "abc\n" would pass and could forge log lines.
        assert is_valid_cid("abc\n") is False
        assert is_valid_cid("legit-cid\nForged: synced /etc/passwd\n") is False


class TestEventModel:
    def test_event_with_file_src(self):
        src = File(filepath="/base/subdir/file.txt", size=10)
        event = Event(
            cid="client1",
            localpath="/base",
            bucket="mybucket",
            name=EventName.added,
            src=src,
        )
        assert event.cid == "client1"
        assert event.bucket == "mybucket"
        assert event.name == "added"
        # Path should have /base stripped
        assert event.src.filepath == "subdir/file.txt"  # type: ignore[reportAttributeAccessIssue]

    def test_event_with_dir_src(self):
        src = Dir(path="/base/mydir")
        event = Event(
            cid="c",
            localpath="/base",
            bucket="b",
            name=EventName.added,
            src=src,
        )
        assert event.src.path == "mydir"  # type: ignore[reportAttributeAccessIssue]

    def test_event_to_dict(self):
        src = File(filepath="/base/f.txt", size=5)
        event = Event(cid="c", localpath="/base", bucket="b", name=EventName.modified, src=src)
        d = event.to_dict()
        assert "cid" in d
        assert "name" in d
        assert "bucket" in d
        assert "src" in d
        assert d["dst"] is None

    def test_event_with_dst(self):
        src = File(filepath="/base/old.txt", size=5)
        dst = File(filepath="/base/new.txt", size=5)
        event = Event(
            cid="c",
            localpath="/base",
            bucket="b",
            name=EventName.renamed,
            src=src,
            dst=dst,
        )
        assert event.dst is not None
        assert event.dst.filepath == "new.txt"  # type: ignore[reportAttributeAccessIssue]

    def test_event_normalizes_src_and_dst_in_place(self):
        # Event rewrites the caller's src/dst objects (documented contract):
        # the same instances appear, normalized, on the event.
        src = File(filepath="/base/old.txt", size=5)
        dst = File(filepath="/base/new.txt", size=5)
        event = Event(
            cid="c",
            localpath="/base",
            bucket="b",
            name=EventName.renamed,
            src=src,
            dst=dst,
        )
        assert event.src is src
        assert event.dst is dst
        assert src.filepath == "old.txt"
        assert dst.filepath == "new.txt"

    def test_shared_string_prefix_is_not_stripped(self):
        # "/base2" merely shares the leading characters of "/base" — it is
        # NOT inside it. String-prefix stripping would mangle the path to
        # "2/x.txt"; component-aware stripping must keep it verbatim.
        src = File(filepath="/base2/x.txt", size=1)
        event = Event(cid="c", localpath="/base", bucket="b", name=EventName.added, src=src)
        assert event.src.filepath == "/base2/x.txt"  # type: ignore[reportAttributeAccessIssue]

    def test_localpath_with_trailing_slash_strips_cleanly(self):
        src = File(filepath="/base/sub/f.txt", size=1)
        event = Event(cid="c", localpath="/base/", bucket="b", name=EventName.added, src=src)
        assert event.src.filepath == "sub/f.txt"  # type: ignore[reportAttributeAccessIssue]

    def test_event_without_strip_prepends_localpath(self):
        src = File(filepath="sub/f.txt", size=5)
        event = Event(
            cid="c",
            localpath="/base",
            bucket="b",
            name=EventName.added,
            src=src,
            strip_localpath=False,
        )
        assert event.src.filepath == "/base/sub/f.txt"  # type: ignore[reportAttributeAccessIssue]

    def test_event_with_dir_without_strip(self):
        src = Dir(path="mydir")
        event = Event(
            cid="c",
            localpath="/base",
            bucket="b",
            name=EventName.added,
            src=src,
            strip_localpath=False,
        )
        assert event.src.path == "/base/mydir"  # type: ignore[reportAttributeAccessIssue]

    def test_event_repr_contains_fields(self):
        src = File(filepath="/base/f.txt", size=5)
        event = Event(cid="cid-1", localpath="/base", bucket="bk", name=EventName.added, src=src)
        text = repr(event)
        assert "Event(" in text
        assert "cid-1" in text
        assert "bk" in text


# =============================================================================
# TombstoneStore
# =============================================================================


class TestTombstoneStore:
    def test_record_and_get(self):
        store = TombstoneStore()
        store.record("a/b.txt", sha256sum="deadbeef", origin_cid=_CID_A, timestamp=1000)
        entry = store.get("a/b.txt")
        assert entry is not None
        assert entry["ts"] == 1000
        assert entry["sha256"] == "deadbeef"
        assert entry["origin_cid"] == _CID_A
        assert entry["vclock"] == {_CID_A: 1}  # deletion tick, not wall clock

    def test_get_missing_returns_none(self):
        assert TombstoneStore().get("nope.txt") is None

    def test_record_inherits_prev_clock_and_ticks(self):
        """The recorded clock inherits the path's version clock and is ticked
        by the deleter, so delete-vs-recreate is causal (ADR-0003)."""
        store = TombstoneStore()
        store.record(
            "f.txt",
            sha256sum="new",
            origin_cid=_CID_A,
            prev_vclock={_CID_B: 3},
            timestamp=20,
        )
        entry = store.get("f.txt")
        assert entry is not None
        assert entry["vclock"] == {_CID_B: 3, _CID_A: 1}

    def test_record_without_origin_keeps_inherited_clock(self):
        store = TombstoneStore()
        store.record("f.txt", prev_vclock={_CID_B: 3}, timestamp=20)
        entry = store.get("f.txt")
        assert entry is not None
        assert entry["vclock"] == {_CID_B: 3}
        assert entry["origin_cid"] is None

    def test_record_replaces_previous_local_marker(self):
        """A local record is an unconditional mutation (no ts comparison)."""
        store = TombstoneStore()
        store.record("f.txt", sha256sum="old", origin_cid=_CID_A, timestamp=10)
        store.record("f.txt", sha256sum="new", origin_cid=_CID_A, timestamp=5)
        entry = store.get("f.txt")
        assert entry is not None
        assert entry["sha256"] == "new"

    def test_record_and_merge_consistent_on_equal_clocks(self):
        """record() and merge() follow the same causal rule: a local record
        advances the clock, so a stale remote marker with an equal clock and
        a lower content hash is kept out by the deterministic tie-break."""
        now = int(time.time())
        key = tombstone_key("f.txt")
        store = TombstoneStore()
        store.record("f.txt", sha256sum="f" * 64, origin_cid=_CID_A, timestamp=now)
        # Remote marker with an identical (non-dominating) clock and lower sha.
        changed = store.merge({key: _tomb("a" * 64, {_CID_A: 1}, now)})
        assert changed == 0
        assert store.get("f.txt")["sha256"] == "f" * 64

    def test_clear(self):
        store = TombstoneStore()
        store.record("f.txt", timestamp=1)
        assert store.clear("f.txt") is True
        assert store.get("f.txt") is None
        assert store.clear("f.txt") is False

    def test_prune_removes_expired(self):
        store = TombstoneStore(ttl_days=1)
        store.record("old.txt", timestamp=0)
        store.record("fresh.txt", timestamp=100_000)
        removed = store.prune(now=100_000)
        assert removed == 1
        assert store.get("old.txt") is None
        assert store.get("fresh.txt") is not None

    def test_prune_disabled_when_ttl_zero(self):
        store = TombstoneStore(ttl_days=0)
        store.record("old.txt", timestamp=0)
        assert store.prune(now=10**12) == 0
        assert store.get("old.txt") is not None

    def test_merge_causal_dominance(self):
        """The merge keeps the causally dominant clock, never the newest ts."""
        now = int(time.time())
        sha_local = "a" * 64
        sha_remote = "b" * 64
        sha_newpath = "c" * 64
        store = TombstoneStore()
        store.record("a.txt", sha256sum=sha_local, origin_cid=_CID_A, timestamp=now - 10)
        # a.txt: remote clock {A:2} dominates local {A:1} → adopt even though
        # its ts (now - 20) is OLDER than the local one (now - 10).
        payload = {
            tombstone_key("a.txt"): _tomb(sha_remote, {_CID_A: 2}, now - 20),
            tombstone_key("b.txt"): _tomb(sha_newpath, {_CID_B: 1}, now - 20),
        }
        changed = store.merge(payload)
        assert changed == 2
        entry_a = store.get("a.txt")
        assert entry_a is not None
        assert entry_a["sha256"] == sha_remote
        entry_b = store.get("b.txt")
        assert entry_b is not None
        assert entry_b["sha256"] == sha_newpath
        # A dominated (ancestor) remote marker must be kept out, regardless of
        # a newer ts.
        assert store.merge({tombstone_key("a.txt"): _tomb("d" * 64, {_CID_A: 1}, now + 1000)}) == 0  # type: ignore[reportArgumentType]
        entry_a = store.get("a.txt")
        assert entry_a is not None
        assert entry_a["sha256"] == sha_remote

    def test_merge_concurrent_tie_break_deterministic(self):
        """Concurrent delete-delete decides by content lineage, never by ts."""
        now = int(time.time())
        store = TombstoneStore()
        store.record("f.txt", sha256sum="a" * 64, origin_cid=_CID_A, timestamp=now)
        # Concurrent clock {B:1} vs {A:1}; incoming sha "f"*64 sorts higher.
        changed = store.merge({tombstone_key("f.txt"): _tomb("f" * 64, {_CID_B: 1}, now - 500)})
        assert changed == 1
        assert store.get("f.txt")["sha256"] == "f" * 64
        # And a concurrent marker with a lower sha is kept out (its newer ts
        # must not matter).
        assert store.merge({tombstone_key("f.txt"): _tomb("a" * 64, {_CID_A: 1}, now + 250)}) == 0
        assert store.get("f.txt")["sha256"] == "f" * 64

    def test_merge_ignores_malformed_entries(self):
        store = TombstoneStore()
        assert store.merge({"k": {"sha256": "no-ts"}}) == 0  # type: ignore[reportArgumentType]
        assert store.merge(None) == 0

    def test_merge_rejects_entries_without_vclock(self):
        """A marker without a valid causal clock is not a legal deletion."""
        now = int(time.time())
        key = tombstone_key("victim.txt")
        store = TombstoneStore()
        # ts + sha present but vclock missing → dropped.
        assert store.merge({key: {"ts": now, "sha256": None}}) == 0  # type: ignore[reportArgumentType]
        # Malformed vclock shapes → dropped.
        assert store.merge({key: _tomb(None, {}, now) | {"vclock": [{"a": 1}]}}) == 0  # type: ignore[reportArgumentType]
        assert store.merge({key: _tomb(None, {_CID_A: -1}, now)}) == 0  # type: ignore[reportArgumentType]
        assert store.merge({key: _tomb(None, {"bad-key!": 1}, now)}) == 0  # type: ignore[reportArgumentType]
        assert len(store) == 0

    def test_merge_rejects_poisoned_entries(self):
        """Anti-poisoning: gossip payloads are untrusted input."""
        now = int(time.time())
        key = tombstone_key("victim.txt")
        store = TombstoneStore()
        # Far-future timestamp (permanent poison) is rejected.
        assert store.merge({key: _tomb(None, {_CID_A: 1}, now + 10_000_000)}) == 0
        assert store.get("victim.txt") is None
        # Non-hex / short keys are rejected.
        assert store.merge({"not-a-sha": _tomb(None, {_CID_A: 1}, now)}) == 0  # type: ignore[reportArgumentType]
        # Malformed content hash is rejected.
        assert store.merge({key: _tomb("not-hex", {_CID_A: 1}, now)}) == 0  # type: ignore[reportArgumentType]
        # Missing/non-numeric/zero timestamps are rejected.
        assert store.merge({key: {"sha256": None, "vclock": {_CID_A: 1}}}) == 0  # type: ignore[reportArgumentType]
        assert store.merge({key: _tomb(None, {_CID_A: 1}, 0)}) == 0  # type: ignore[reportArgumentType]
        assert store.merge({key: {"ts": "soon", "sha256": None, "vclock": {_CID_A: 1}}}) == 0  # type: ignore[reportArgumentType]
        assert len(store) == 0

    def test_merge_rejects_non_finite_and_bool_timestamps(self):
        """json.loads accepts Infinity/NaN: int() would then raise
        OverflowError/ValueError — the merge must reject, not crash."""
        now = int(time.time())
        key = tombstone_key("victim.txt")
        store = TombstoneStore()
        assert store.merge({key: _tomb(None, {_CID_A: 1}, float("inf"))}) == 0  # type: ignore[reportArgumentType]
        assert store.merge({key: _tomb(None, {_CID_A: 1}, float("-inf"))}) == 0  # type: ignore[reportArgumentType]
        assert store.merge({key: _tomb(None, {_CID_A: 1}, float("nan"))}) == 0  # type: ignore[reportArgumentType]
        assert store.merge({key: _tomb(None, {_CID_A: 1}, True)}) == 0  # type: ignore[reportArgumentType]
        assert len(store) == 0
        # A legitimate float timestamp still converts cleanly.
        assert store.merge({key: _tomb(None, {_CID_A: 1}, float(now))}) == 1
        assert store.get("victim.txt") is not None

    def test_merge_accepts_timestamp_within_clock_skew(self):
        now = int(time.time())
        key = tombstone_key("victim.txt")
        store = TombstoneStore()
        # A timestamp within the clock-skew tolerance is accepted.
        assert store.merge({key: _tomb(None, {_CID_A: 1}, now + 60)}) == 1
        assert store.get("victim.txt") is not None

    def test_merge_caps_store_size(self, monkeypatch):
        monkeypatch.setattr("hsync_common.models.tombstone.TOMBSTONE_MAX_ENTRIES", 2)
        now = int(time.time())
        store = TombstoneStore()
        payload = {tombstone_key(f"f{i}.txt"): _tomb(None, {_CID_A: i + 1}, now) for i in range(5)}
        store.merge(payload)
        assert len(store) == 2

    def test_to_payload_roundtrips_through_merge(self):
        now = int(time.time())
        src = TombstoneStore()
        src.record("a/b.txt", sha256sum="e" * 64, origin_cid=_CID_A, timestamp=now)
        dst = TombstoneStore()
        dst.merge(src.to_payload())
        assert dst.get("a/b.txt") == src.get("a/b.txt")

    def test_save_and_load(self, tmp_path):
        now = int(time.time())
        folder_id = "22222222-2222-4222-8222-222222222222"
        db_path = str(tmp_path / "syncstate.db")
        store = TombstoneStore(db_path=db_path, folder_id=folder_id, ttl_days=90)
        store.record("a/b.txt", sha256sum="f" * 64, origin_cid=_CID_A, timestamp=now)
        store.save()

        reloaded = TombstoneStore(db_path=db_path, folder_id=folder_id, ttl_days=90)
        reloaded.load()
        entry = reloaded.get("a/b.txt")
        assert entry is not None
        assert entry["ts"] == now
        assert entry["sha256"] == "f" * 64
        assert entry["vclock"] == {_CID_A: 1}

    def test_load_drops_poisoned_entries(self, tmp_path):
        from hsync_common.models.sqlstore import get_state_db

        now = int(time.time())
        folder_id = "22222222-2222-4222-8222-222222222222"
        db_path = str(tmp_path / "syncstate.db")
        store = TombstoneStore(db_path=db_path, folder_id=folder_id)
        store.load()
        db = get_state_db(db_path)

        def _insert(key, sha, ts, vclock):
            db.conn.execute(
                """
                INSERT INTO tombstones
                  (folder_id, key, sha256sum, version_id, origin_cid, ts, vclock)
                VALUES (?, ?, ?, 'v', NULL, ?, ?)
                """,
                (folder_id, key, sha, ts, vclock),
            )

        _insert(tombstone_key("ok.txt"), None, now, json.dumps({_CID_A: 1}))
        _insert(tombstone_key("future.txt"), None, now + 10_000_000, json.dumps({_CID_A: 1}))
        _insert("bad-key", None, now, json.dumps({_CID_A: 1}))
        _insert(tombstone_key("badsha.txt"), "xyz", now, json.dumps({_CID_A: 1}))
        _insert(tombstone_key("novclock.txt"), None, now, "")
        _insert(tombstone_key("negclock.txt"), None, now, json.dumps({_CID_A: -1}))
        store.load()
        assert len(store) == 1
        assert store.get("ok.txt") is not None

    def test_load_missing_db_is_empty(self, tmp_path):
        store = TombstoneStore(
            db_path=str(tmp_path / "absent.db"),
            folder_id="22222222-2222-4222-8222-222222222222",
        )
        store.load()
        assert len(store) == 0

    def test_save_without_backend_is_noop(self):
        store = TombstoneStore()
        store.record("x.txt")
        store.save()

    def test_merge_rejects_non_dict_payload(self):
        # Gossip payloads are untrusted: a JSON array/string must be ignored,
        # not crash the merge with AttributeError.
        store = TombstoneStore()
        assert store.merge(["not", "a", "dict"]) == 0  # type: ignore[arg-type]
        assert store.merge("string") == 0  # type: ignore[arg-type]
        assert store.merge(None) == 0
        assert len(store) == 0


class TestRelpathInBucket:
    def test_strips_bucket_prefix_and_leading_slash(self):
        assert relpath_in_bucket("/bucket/a/b.txt", "/bucket") == "a/b.txt"

    def test_handles_trailing_slash_on_bucket(self):
        assert relpath_in_bucket("/bucket/a/b.txt", "/bucket/") == "a/b.txt"

    def test_bucket_root_yields_empty(self):
        # The bucket itself maps to the empty (root) relative path.
        assert relpath_in_bucket("/bucket", "/bucket") == ""

    def test_component_aware_normalisation(self):
        # Duplicate separators, "." components and a trailing separator are
        # collapsed/dropped, exactly as the previous Path.relative_to
        # implementation behaved.
        assert relpath_in_bucket("/bucket//a/./b.txt", "/bucket") == "a/b.txt"
        assert relpath_in_bucket("/bucket/a/b.txt/", "/bucket") == "a/b.txt"

    def test_dotdot_is_preserved_not_resolved(self):
        # ".." is never resolved: boundary checks live in path_validation, and
        # resolving here would silently relocate the identity of a path
        # (Path.relative_to kept ".." verbatim too).
        assert relpath_in_bucket("/bucket/a/../b.txt", "/bucket") == "a/../b.txt"

    def test_sibling_prefix_is_not_stripped(self):
        assert relpath_in_bucket("/bucket2/a.txt", "/bucket") is None

    def test_empty_bucket_means_nothing_inside(self):
        # ``p2p_server`` reads LOCAL_BUCKET with a "" default: an empty bucket
        # must never turn an absolute path into a valid relative identity.
        assert relpath_in_bucket("/bucket/a.txt", "") is None
        assert relpath_in_bucket("", "") is None

    def test_path_outside_bucket_returns_none(self):
        # A path outside the bucket must never be confused with an in-bucket
        # path (never the bucket-root identity "" nor the raw input, which could
        # be smuggled into a tombstone key and corrupt the root's state).
        assert relpath_in_bucket("/other/a.txt", "/bucket") is None
