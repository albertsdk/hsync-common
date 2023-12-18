"""Tests for hsync_common models (File, Dir, Symlink, Event, SyncAction)."""

import os
import stat
import tempfile
from datetime import UTC, datetime

import pytest

from hsync_common.models.dir import Dir, is_hidden_dir
from hsync_common.models.event import Event, EventName
from hsync_common.models.file import (
    MD5_CACHE_MAX_SIZE,
    File,
    _md5_cache,
    _set_cached_md5,
    clear_md5_cache,
    invalidate_md5_cache,
    is_hidden_file,
)
from hsync_common.models.symlink import Symlink
from hsync_common.models.sync_action import SyncAction, SyncActionName


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


class TestFileInit:
    def test_basic_init(self):
        f = File(filepath="/tmp/test.txt", size=100, md5sum="abc123")
        assert f.filepath == "/tmp/test.txt"
        assert f.name == "test.txt"
        assert f.size == 100
        assert f.md5sum == "abc123"

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
        assert "md5sum" in d


class TestFileMd5Cache:
    def test_clear_cache_does_not_raise(self):
        clear_md5_cache()

    def test_invalidate_nonexistent_does_not_raise(self):
        invalidate_md5_cache("/nonexistent/path.txt")

    def test_md5_cache_max_size_constant(self):
        """O2: MD5_CACHE_MAX_SIZE must be a positive integer."""
        assert isinstance(MD5_CACHE_MAX_SIZE, int)
        assert MD5_CACHE_MAX_SIZE > 0

    def test_cache_evicts_oldest_when_full(self):
        """O2: inserting beyond MD5_CACHE_MAX_SIZE evicts the LRU entry."""
        clear_md5_cache()
        # Fill the cache to the limit using fake paths
        for i in range(MD5_CACHE_MAX_SIZE):
            _set_cached_md5(f"/fake/path/{i}.txt", "a" * 32, i)
        assert len(_md5_cache) == MD5_CACHE_MAX_SIZE

        # Adding one more entry should evict the oldest (/fake/path/0.txt)
        _set_cached_md5("/fake/path/overflow.txt", "b" * 32, 9999)
        assert len(_md5_cache) == MD5_CACHE_MAX_SIZE
        assert "/fake/path/0.txt" not in _md5_cache
        assert "/fake/path/overflow.txt" in _md5_cache

        clear_md5_cache()  # clean up for subsequent tests


class TestFileGet:
    def test_get_existing_file(self, tmp_path):
        f = tmp_path / "real.txt"
        f.write_text("hello")
        result = File.get(str(f))
        assert result is not None
        assert result.size == 5
        assert result.md5sum is not None

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


class TestDirModel:
    def test_init(self):
        d = Dir(path="/tmp/sync", permissions="drwxr-xr-x")
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
            cid="c", localpath="/base", bucket="b",
            name=EventName.added, src=src,
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
            cid="c", localpath="/base", bucket="b",
            name=EventName.renamed, src=src, dst=dst,
        )
        assert event.dst is not None
        assert event.dst.filepath == "new.txt"
