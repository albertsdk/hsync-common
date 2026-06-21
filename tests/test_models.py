"""Tests for hsync_common models (File, Dir, Symlink, Event, SyncAction)."""

import json
import time
from datetime import UTC, datetime

import pytest

from hsync_common.constants import (
    CHUNK_SIZE_LARGE,
    CHUNK_SIZE_MEDIUM,
    CHUNK_SIZE_SMALL,
    FILE_SIZE_MEDIUM,
    FILE_SIZE_SMALL,
)
from hsync_common.models.dir import Dir, is_hidden_dir
from hsync_common.models.event import Event, EventName
from hsync_common.models.file import (
    SHA256_CACHE_MAX_SIZE,
    File,
    _get_cached_sha256,
    _set_cached_sha256,
    _sha256_cache,
    clear_sha256_cache,
    invalidate_sha256_cache,
    is_hidden_file,
    is_partial_file,
)
from hsync_common.models.symlink import Symlink
from hsync_common.models.sync_action import SyncAction, SyncActionName
from hsync_common.models.tombstone import (
    TombstoneStore,
    relpath_in_bucket,
    tombstone_key,
)

# =============================================================================
# File model
# =============================================================================


class TestIsHiddenFile:
    def test_dot_file_is_hidden(self):
        assert is_hidden_file(".hidden") is True

    def test_regular_file_not_hidden(self):
        assert is_hidden_file("document.txt") is False

    def test_tilde_backup_is_hidden(self):
        assert is_hidden_file("file.txt~") is True

    def test_vim_swap_is_hidden(self):
        assert is_hidden_file(".file.swp") is True

    def test_hsynckeep_not_hidden(self):
        from hsync_common.constants import HSYNCKEEP_FILENAME

        assert is_hidden_file(HSYNCKEEP_FILENAME) is False

    def test_bak_is_hidden(self):
        assert is_hidden_file("backup.bak") is True

    def test_tmp_is_hidden(self):
        assert is_hidden_file("temp.tmp") is True

    def test_partial_download_is_hidden(self):
        assert is_hidden_file("document.txt.part") is True


class TestIsPartialFile:
    def test_partial_suffix_detected(self):
        assert is_partial_file("document.txt.part") is True

    def test_partial_suffix_detected_with_path(self):
        assert is_partial_file("dir/sub/document.txt.part") is True

    def test_regular_file_not_partial(self):
        assert is_partial_file("document.txt") is False

    def test_part_in_name_only_not_partial(self):
        assert is_partial_file("part.txt") is False


class TestFileInit:
    def test_basic_init(self):
        f = File(filepath="/tmp/test.txt", size=100, sha256sum="abc123")
        assert f.filepath == "/tmp/test.txt"
        assert f.name == "test.txt"
        assert f.size == 100
        assert f.sha256sum == "abc123"

    def test_none_filepath(self):
        f = File()
        assert f.filepath is None
        assert f.name is None

    def test_time_as_int(self):
        f = File(mtime=1_000_000)
        assert f.mtime == 1_000_000

    def test_time_as_datetime(self):
        dt = datetime(2025, 1, 1, tzinfo=UTC)
        f = File(mtime=dt)
        assert f.mtime == int(dt.timestamp())

    def test_time_as_isoformat_string(self):
        f = File(mtime="2025-01-01T00:00:00+00:00")
        assert isinstance(f.mtime, int)

    def test_none_time(self):
        f = File()
        assert f.ctime is None
        assert f.mtime is None


class TestFileToDict:
    def test_to_dict_keys(self):
        f = File(filepath="/tmp/a.txt", size=10)
        d = f.to_dict()
        assert "filepath" in d
        assert "name" in d
        assert "size" in d
        assert "sha256sum" in d


class TestFileSha256Cache:
    def test_clear_cache_does_not_raise(self):
        clear_sha256_cache()

    def test_invalidate_nonexistent_does_not_raise(self):
        invalidate_sha256_cache("/nonexistent/path.txt")

    def test_sha256_cache_max_size_constant(self):
        """O2: sha256_cache_MAX_SIZE must be a positive integer."""
        assert isinstance(SHA256_CACHE_MAX_SIZE, int)
        assert SHA256_CACHE_MAX_SIZE > 0

    def test_cache_evicts_oldest_when_full(self):
        """O2: inserting beyond sha256_cache_MAX_SIZE evicts the LRU entry."""
        clear_sha256_cache()
        # Fill the cache to the limit using fake paths
        for i in range(SHA256_CACHE_MAX_SIZE):
            _set_cached_sha256(f"/fake/path/{i}.txt", "a" * 32, i)
        assert len(_sha256_cache) == SHA256_CACHE_MAX_SIZE

        # Adding one more entry should evict the oldest (/fake/path/0.txt)
        _set_cached_sha256("/fake/path/overflow.txt", "b" * 32, 9999)
        assert len(_sha256_cache) == SHA256_CACHE_MAX_SIZE
        assert "/fake/path/0.txt" not in _sha256_cache
        assert "/fake/path/overflow.txt" in _sha256_cache

        clear_sha256_cache()  # clean up for subsequent tests

    def test_cache_hit_returns_value_and_moves_to_end(self):
        """A hit with matching mtime returns the cached sum and refreshes LRU order."""
        clear_sha256_cache()
        _set_cached_sha256("/a.txt", "a" * 64, mtime=10)
        _set_cached_sha256("/b.txt", "b" * 64, mtime=20)
        # Hitting the oldest entry should move it to the end (most-recent).
        assert _get_cached_sha256("/a.txt", 10) == "a" * 64
        assert next(reversed(_sha256_cache)) == "/a.txt"
        clear_sha256_cache()

    def test_cache_miss_on_mtime_change_evicts_entry(self):
        """A stale mtime drops the entry and returns None."""
        clear_sha256_cache()
        _set_cached_sha256("/c.txt", "c" * 64, mtime=10)
        assert _get_cached_sha256("/c.txt", 11) is None
        assert "/c.txt" not in _sha256_cache
        clear_sha256_cache()

    def test_cache_miss_on_unknown_path(self):
        clear_sha256_cache()
        assert _get_cached_sha256("/never-seen.txt", 1) is None


class TestComputeSha256ChunkSize:
    """The adaptive chunk size must not change the resulting digest."""

    def _expected(self, content: bytes) -> str:
        from hashlib import sha256

        return sha256(content).hexdigest()

    @pytest.mark.parametrize(
        "file_size",
        [None, 0, FILE_SIZE_SMALL, FILE_SIZE_MEDIUM],
    )
    def test_digest_is_stable_across_chunk_branches(self, tmp_path, file_size):
        content = b"chunk-size-branch-content"
        f = tmp_path / "blob.bin"
        f.write_bytes(content)
        digest = File._compute_sha256(str(f), file_size=file_size)
        assert digest == self._expected(content)

    def test_chunk_constants_are_ordered(self):
        assert CHUNK_SIZE_SMALL < CHUNK_SIZE_MEDIUM < CHUNK_SIZE_LARGE


class TestFileRepr:
    def test_repr_contains_fields(self):
        f = File(filepath="/tmp/r.txt", size=7, sha256sum="deadbeef")
        text = repr(f)
        assert "File(" in text
        assert "/tmp/r.txt" in text
        assert "deadbeef" in text


class TestFileGet:
    def test_get_existing_file(self, tmp_path):
        f = tmp_path / "real.txt"
        f.write_text("hello")
        result = File.get(str(f))
        assert result is not None
        assert result.size == 5
        assert result.sha256sum is not None

    def test_get_nonexistent_returns_none(self):
        assert File.get("/nonexistent/path/file.txt") is None

    def test_get_with_buckets_dir(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_bytes(b"data")
        result = File.get("data.txt", buckets_dir=str(tmp_path))
        assert result is not None


class TestFileFromDict:
    def test_from_dict_with_strip(self):
        d = {"filepath": "/base/subdir/file.txt", "size": 50}
        f = File.from_dict(d, dir_prefix="/base", strip_dir_prefix=True)
        assert f.filepath == "subdir/file.txt"

    def test_from_dict_without_strip(self):
        d = {"filepath": "subdir/file.txt", "size": 50}
        f = File.from_dict(d, dir_prefix="/base", strip_dir_prefix=False)
        assert "/base" in f.filepath

    def test_from_dict_raises_if_strip_without_prefix(self):
        d = {"filepath": "/base/file.txt", "size": 10}
        with pytest.raises(ValueError):
            File.from_dict(d, dir_prefix=None, strip_dir_prefix=True)

    def test_from_dict_no_prefix_keeps_filepath(self):
        f = File.from_dict({"filepath": "plain.txt", "size": 1}, strip_dir_prefix=False)
        assert f.filepath == "plain.txt"


# =============================================================================
# Dir model
# =============================================================================


class TestIsHiddenDir:
    def test_dot_dir_is_hidden(self):
        assert is_hidden_dir(".git") is True

    def test_regular_dir_not_hidden(self):
        assert is_hidden_dir("documents") is False

    def test_parent_dot_dir_is_hidden(self):
        assert is_hidden_dir(".parent/subdir") is True


class TestIsHiddenMatcherAwareness:
    """is_hidden_dir/is_hidden_file consult the active IgnoreMatcher (2.14).

    The matcher-aware behaviour now lives in hsync_common, so importing the
    functions from common, client or server yields identical results. The
    private ``_basic`` helpers remain the matcher's own fallback to avoid
    infinite recursion.
    """

    @pytest.fixture
    def active_secret_matcher(self, tmp_path):
        from hsync_common.constants import HSYNCIGNORE_FILENAME
        from hsync_common.ignore import IgnoreMatcher, set_active_matcher

        (tmp_path / HSYNCIGNORE_FILENAME).write_text("*.secret\nbuild/\n")
        # include_hidden=False keeps the built-in hidden fallback active, which
        # exercises the recursion-prone path (matcher -> _is_hidden_*_basic).
        matcher = IgnoreMatcher(str(tmp_path), include_hidden=False)
        set_active_matcher(matcher)
        try:
            yield tmp_path
        finally:
            set_active_matcher(None)

    def test_no_matcher_uses_basic_file_check(self):
        from hsync_common.ignore import set_active_matcher

        set_active_matcher(None)
        assert is_hidden_file(".hidden") is True
        assert is_hidden_file("foo.secret") is False

    def test_file_consults_active_matcher(self, active_secret_matcher):
        assert is_hidden_file("foo.secret") is True
        assert is_hidden_file("foo.txt") is False

    def test_dir_consults_active_matcher(self, active_secret_matcher):
        assert is_hidden_dir("build") is True
        assert is_hidden_dir("documents") is False

    def test_matcher_active_does_not_recurse(self, active_secret_matcher):
        # A path matching no rule falls through to the matcher's hidden-check,
        # which must use the pure helper (no re-entry into is_hidden_*).
        assert is_hidden_file(".env") is True
        assert is_hidden_dir(".cache") is True


class TestDirModel:
    def test_init(self):
        d = Dir(path="/tmp/sync", permissions="755")
        assert d.path == "/tmp/sync"

    def test_to_dict(self):
        d = Dir(path="/tmp/sync")
        result = d.to_dict()
        assert "path" in result
        assert "permissions" in result

    def test_get_existing(self, tmp_path):
        d = Dir.get(str(tmp_path))
        assert d is not None

    def test_get_nonexistent(self):
        assert Dir.get("/nonexistent/1234") is None

    def test_from_dict(self):
        d = Dir.from_dict({"path": "subdir"}, localpath="/base", strip_localpath=False)
        assert "/base" in d.path

    def test_repr_contains_fields(self):
        d = Dir(path="/tmp/sync", permissions="755")
        text = repr(d)
        assert "Dir(" in text
        assert "/tmp/sync" in text
        assert "755" in text


# =============================================================================
# Symlink model
# =============================================================================


class TestSymlinkModel:
    def test_init(self):
        s = Symlink(filepath="/tmp/link.txt", target="/tmp/real.txt")
        assert s.name == "link.txt"
        assert s.target == "/tmp/real.txt"

    def test_to_dict(self):
        s = Symlink(filepath="/tmp/link.txt", target="/tmp/real.txt")
        d = s.to_dict()
        assert d["type"] == "symlink"
        assert "filepath" in d
        assert "target" in d

    def test_from_dict(self):
        s = Symlink.from_dict({"filepath": "/a/link", "target": "/b/real"})
        assert s.filepath == "/a/link"
        assert s.target == "/b/real"

    def test_get_nonexistent(self):
        assert Symlink.get("/nonexistent/link") is None

    def test_get_real_symlink(self, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("data")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        result = Symlink.get(str(link))
        assert result is not None
        assert result.target == str(target)

    def test_get_regular_file_returns_none(self, tmp_path):
        # An existing path that is not a symlink must be rejected.
        regular = tmp_path / "regular.txt"
        regular.write_text("data")
        assert Symlink.get(str(regular)) is None

    def test_get_oserror_returns_none(self, tmp_path, monkeypatch):
        target = tmp_path / "t.txt"
        target.write_text("data")
        link = tmp_path / "l.txt"
        link.symlink_to(target)

        import hsync_common.models.symlink as symlink_mod

        def _boom(*_args, **_kwargs):
            raise OSError("readlink failed")

        monkeypatch.setattr(symlink_mod, "readlink", _boom)
        assert Symlink.get(str(link)) is None

    def test_repr_contains_fields(self):
        s = Symlink(filepath="/tmp/link.txt", target="/tmp/real.txt")
        text = repr(s)
        assert "Symlink(" in text
        assert "/tmp/link.txt" in text
        assert "/tmp/real.txt" in text


# =============================================================================
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


class TestEventModel:
    def test_event_with_file_src(self):
        src = File(filepath="/base/subdir/file.txt", size=10)
        event = Event(
            cid="client-1",
            localpath="/base",
            bucket="mybucket",
            name=EventName.added,
            src=src,
        )
        assert event.cid == "client-1"
        assert event.bucket == "mybucket"
        assert event.name == "added"
        # Path should have /base stripped
        assert event.src.filepath == "subdir/file.txt"

    def test_event_with_dir_src(self):
        src = Dir(path="/base/mydir")
        event = Event(
            cid="c",
            localpath="/base",
            bucket="b",
            name=EventName.added,
            src=src,
        )
        assert event.src.path == "mydir"

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
        assert event.dst.filepath == "new.txt"

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
        assert event.src.filepath == "/base/sub/f.txt"

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
        assert event.src.path == "/base/mydir"

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
        store.record("a/b.txt", sha256sum="deadbeef", timestamp=1000)
        entry = store.get("a/b.txt")
        assert entry is not None
        assert entry["ts"] == 1000
        assert entry["sha256"] == "deadbeef"

    def test_get_missing_returns_none(self):
        assert TombstoneStore().get("nope.txt") is None

    def test_get_by_key_matches_hashed_path(self):
        store = TombstoneStore()
        store.record("a/b.txt", timestamp=5)
        assert store.get_by_key(tombstone_key("a/b.txt")) is not None

    def test_record_is_last_writer_wins(self):
        store = TombstoneStore()
        store.record("f.txt", sha256sum="old", timestamp=10)
        store.record("f.txt", sha256sum="new", timestamp=20)
        assert store.get("f.txt")["sha256"] == "new"
        # An older marker must not overwrite a newer one.
        store.record("f.txt", sha256sum="stale", timestamp=5)
        assert store.get("f.txt")["sha256"] == "new"

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

    def test_merge_lww(self):
        now = int(time.time())
        sha_local = "a" * 64
        sha_remote = "b" * 64
        sha_newpath = "c" * 64
        store = TombstoneStore()
        store.record("a.txt", sha256sum=sha_local, timestamp=now - 10)
        payload = {
            tombstone_key("a.txt"): {"ts": now, "sha256": sha_remote},
            tombstone_key("b.txt"): {"ts": now - 20, "sha256": sha_newpath},
        }
        changed = store.merge(payload)
        assert changed == 2
        assert store.get("a.txt")["sha256"] == sha_remote
        assert store.get("b.txt")["sha256"] == sha_newpath
        # Older remote entry must not override newer local one.
        assert store.merge({tombstone_key("a.txt"): {"ts": now - 30, "sha256": "d" * 64}}) == 0
        assert store.get("a.txt")["sha256"] == sha_remote

    def test_merge_ignores_malformed_entries(self):
        store = TombstoneStore()
        assert store.merge({"k": {"sha256": "no-ts"}}) == 0
        assert store.merge(None) == 0

    def test_merge_rejects_poisoned_entries(self):
        """Anti-poisoning: gossip payloads are untrusted input."""
        now = int(time.time())
        key = tombstone_key("victim.txt")
        store = TombstoneStore()
        # Far-future timestamp (permanent poison) is rejected.
        assert store.merge({key: {"ts": now + 10_000_000, "sha256": None}}) == 0
        assert store.get("victim.txt") is None
        # Non-hex / short keys are rejected.
        assert store.merge({"not-a-sha": {"ts": now, "sha256": None}}) == 0
        # Malformed content hash is rejected.
        assert store.merge({key: {"ts": now, "sha256": "not-hex"}}) == 0
        # Missing/non-numeric/zero timestamps are rejected.
        assert store.merge({key: {"sha256": None}}) == 0
        assert store.merge({key: {"ts": "soon", "sha256": None}}) == 0
        assert store.merge({key: {"ts": 0, "sha256": None}}) == 0
        assert len(store) == 0
        # A timestamp within the clock-skew tolerance is accepted.
        assert store.merge({key: {"ts": now + 60, "sha256": None}}) == 1
        assert store.get("victim.txt") is not None

    def test_merge_caps_store_size(self, monkeypatch):
        monkeypatch.setattr("hsync_common.models.tombstone.TOMBSTONE_MAX_ENTRIES", 2)
        now = int(time.time())
        store = TombstoneStore()
        payload = {tombstone_key(f"f{i}.txt"): {"ts": now, "sha256": None} for i in range(5)}
        store.merge(payload)
        assert len(store) == 2

    def test_to_payload_roundtrips_through_merge(self):
        now = int(time.time())
        src = TombstoneStore()
        src.record("a/b.txt", sha256sum="e" * 64, timestamp=now)
        dst = TombstoneStore()
        dst.merge(src.to_payload())
        assert dst.get("a/b.txt") == src.get("a/b.txt")

    def test_save_and_load(self, tmp_path):
        now = int(time.time())
        path = str(tmp_path / "sub" / ".hsynctombstones")
        store = TombstoneStore(path=path, ttl_days=30)
        store.record("a/b.txt", sha256sum="f" * 64, timestamp=now)
        store.save()

        reloaded = TombstoneStore(path=path, ttl_days=30)
        reloaded.load()
        entry = reloaded.get("a/b.txt")
        assert entry is not None
        assert entry["ts"] == now
        assert entry["sha256"] == "f" * 64

    def test_load_drops_poisoned_entries(self, tmp_path):
        now = int(time.time())
        path = tmp_path / ".hsynctombstones"
        path.write_text(
            json.dumps(
                {
                    "tombstones": {
                        tombstone_key("ok.txt"): {"ts": now, "sha256": None},
                        tombstone_key("future.txt"): {"ts": now + 10_000_000, "sha256": None},
                        "bad-key": {"ts": now, "sha256": None},
                        tombstone_key("badsha.txt"): {"ts": now, "sha256": "xyz"},
                    }
                }
            ),
            encoding="utf-8",
        )
        store = TombstoneStore(path=str(path))
        store.load()
        assert len(store) == 1
        assert store.get("ok.txt") is not None

    def test_load_missing_file_is_noop(self, tmp_path):
        store = TombstoneStore(path=str(tmp_path / "absent.json"))
        store.load()
        assert len(store) == 0

    def test_load_corrupt_file_is_noop(self, tmp_path):
        path = tmp_path / ".hsynctombstones"
        path.write_text("{not json", encoding="utf-8")
        store = TombstoneStore(path=str(path))
        store.load()
        assert len(store) == 0


class TestRelpathInBucket:
    def test_strips_bucket_prefix_and_leading_slash(self):
        assert relpath_in_bucket("/bucket/a/b.txt", "/bucket") == "a/b.txt"

    def test_handles_trailing_slash_on_bucket(self):
        assert relpath_in_bucket("/bucket/a/b.txt", "/bucket/") == "a/b.txt"

    def test_bucket_root_yields_empty(self):
        assert relpath_in_bucket("/bucket", "/bucket") == ""

    def test_path_outside_bucket_is_unchanged(self):
        assert relpath_in_bucket("/other/a.txt", "/bucket") == "other/a.txt"
