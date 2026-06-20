"""Tests for hsync_common.models.version."""

from hsync_common.models.version import (
    FileVersion,
    SyncDecision,
    SyncStateStore,
    new_change_id,
    resolve_three_way,
)


class TestNewChangeId:
    def test_is_hex_string(self):
        cid = new_change_id()
        assert isinstance(cid, str)
        int(cid, 16)  # raises if not hex

    def test_is_unique(self):
        assert new_change_id() != new_change_id()


class TestResolveThreeWay:
    def test_identical_content_is_in_sync(self):
        assert resolve_three_way("h", "h", None) is SyncDecision.in_sync
        assert resolve_three_way("h", "h", "h") is SyncDecision.in_sync

    def test_unknown_base_when_differ(self):
        assert resolve_three_way("a", "b", None) is SyncDecision.unknown_base

    def test_only_local_changed_uploads(self):
        # base == remote, local moved on
        assert resolve_three_way("local", "base", "base") is SyncDecision.upload

    def test_only_remote_changed_downloads(self):
        # base == local, remote moved on
        assert resolve_three_way("base", "remote", "base") is SyncDecision.download

    def test_both_changed_is_conflict(self):
        assert resolve_three_way("a", "b", "base") is SyncDecision.conflict

    def test_local_absent_remote_present(self):
        # None vs content with a known base where local matched base -> download
        assert resolve_three_way(None, "remote", None) is SyncDecision.unknown_base


class TestSyncStateStoreMutation:
    def test_record_and_get(self):
        store = SyncStateStore()
        store.record("a/b.txt", base_hash="hh", change_id="cid", origin_cid="peer1", timestamp=42)
        entry = store.get("a/b.txt")
        assert entry is not None
        assert entry["base_hash"] == "hh"
        assert entry["change_id"] == "cid"
        assert entry["origin_cid"] == "peer1"
        assert entry["ts"] == 42

    def test_record_defaults_change_id_and_ts(self):
        store = SyncStateStore()
        store.record("x.txt", base_hash="hh")
        entry = store.get("x.txt")
        assert entry is not None
        assert entry["change_id"]  # auto-minted, non-empty
        assert entry["origin_cid"] is None
        assert entry["ts"] > 0

    def test_base_hash_helper(self):
        store = SyncStateStore()
        store.record("x.txt", base_hash="hh")
        assert store.base_hash("x.txt") == "hh"
        assert store.base_hash("missing.txt") is None

    def test_record_overwrites(self):
        store = SyncStateStore()
        store.record("x.txt", base_hash="old")
        store.record("x.txt", base_hash="new")
        assert store.base_hash("x.txt") == "new"
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
        store.record("a/b.txt", base_hash="hh", change_id="cid", origin_cid="peer", timestamp=7)
        store.save()

        reloaded = SyncStateStore(path=path)
        reloaded.load()
        entry = reloaded.get("a/b.txt")
        assert entry is not None
        assert entry["base_hash"] == "hh"
        assert entry["change_id"] == "cid"
        assert entry["origin_cid"] == "peer"
        assert entry["ts"] == 7

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

    def test_load_skips_entries_without_base_hash(self, tmp_path):
        import json

        path = tmp_path / ".hsyncstate"
        path.write_text(
            json.dumps({"versions": {"k1": {"change_id": "c"}, "k2": {"base_hash": "h"}}}),
            encoding="utf-8",
        )
        store = SyncStateStore(path=str(path))
        store.load()
        assert len(store) == 1


class TestFileVersionTypedDict:
    def test_construct(self):
        v: FileVersion = {"base_hash": "h", "change_id": "c", "origin_cid": None, "ts": 1}
        assert v["base_hash"] == "h"
