"""Tests for hsync_common models (File, Dir, Symlink, Event, SyncAction)."""

from datetime import UTC, datetime

import pytest

from hsync_common.models.file import (
    SHA256_CACHE_MAX_SIZE,
    File,
    FileDict,
    _get_cached_sha256,
    _set_cached_sha256,
    _sha256_cache,
    clear_sha256_cache,
    invalidate_sha256_cache,
    is_hidden_file,
    is_partial_file,
)

# =============================================================================
# File model
# =============================================================================


class TestIsHiddenFile:
    """Default ignore patterns follow the industry standard: only OS cache
    and editor/office temporary files are excluded. Dotfiles in general
    (.env, .config, .git …) are synchronised normally."""

    def test_dotfile_not_hidden_by_default(self):
        """Dotfiles like .env, .config are synced normally (industry standard)."""
        assert is_hidden_file(".env") is False
        assert is_hidden_file(".config") is False
        assert is_hidden_file(".hidden") is False

    def test_regular_file_not_hidden(self):
        assert is_hidden_file("document.txt") is False

    def test_ds_store_is_hidden(self):
        assert is_hidden_file(".DS_Store") is True

    def test_thumbs_db_is_hidden(self):
        assert is_hidden_file("Thumbs.db") is True

    def test_office_lock_is_hidden(self):
        assert is_hidden_file("~$document.docx") is True

    def test_tilde_backup_is_hidden(self):
        assert is_hidden_file("file.txt~") is True

    def test_vim_swap_is_hidden(self):
        # Vim swap files are dotfiles; the `.*.sw?` pattern deliberately does
        # not match non-hidden names (e.g. `animation.swf` must stay visible).
        assert is_hidden_file(".file.swp") is True
        assert is_hidden_file(".file.swo") is True
        assert is_hidden_file("file.swp") is False
        assert is_hidden_file("file.swo") is False

    def test_hsynckeep_not_hidden(self):
        from hsync_common.constants import HSYNCKEEP_FILENAME

        assert is_hidden_file(HSYNCKEEP_FILENAME) is False

    def test_bak_is_hidden(self):
        assert is_hidden_file("backup.bak") is True

    def test_tmp_is_hidden(self):
        assert is_hidden_file("temp.tmp") is True
        assert is_hidden_file("temp.temp") is True

    def test_partial_download_is_hidden(self):
        assert is_hidden_file("document.txt.part") is True

    def test_internal_files_are_hidden(self):
        assert is_hidden_file(".hsyncignore") is True
        assert is_hidden_file(".hsyncfolder") is True
        assert is_hidden_file(".hsyncstate") is True
        assert is_hidden_file(".hsynctombstones") is True


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
        # Pin the exact parsed value: an int cast of "now" would also satisfy
        # isinstance but would be a parsing regression.
        assert f.mtime == 1735689600

    def test_invalid_time_string_raises(self):
        with pytest.raises(ValueError):
            File(mtime="not-a-timestamp")

    def test_none_time(self):
        f = File()
        assert f.ctime is None
        assert f.mtime is None

    def test_bool_time_rejected_as_none(self):
        # bool is an int subclass: True would silently parse as timestamp 0
        # unless explicitly rejected (same guard as TombstoneStore).
        # _parse_time returns None for unrecognized types, so a bool timestamp
        # is treated the same as an explicit None.
        f = File(mtime=True)
        assert f.mtime is None


class TestFileToDict:
    def test_to_dict_keys(self):
        f = File(filepath="/tmp/a.txt", size=10)
        d = f.to_dict()
        # FileDict is the wire contract (its keys drive the WS schema): the
        # serialized dict must contain exactly the required keys (the optional
        # ``version`` is attached only when set).
        assert set(d) == set(FileDict.__required_keys__)

    def test_to_dict_values(self):
        f = File(filepath="/tmp/a.txt", size=10, sha256sum="ab" * 32, permissions="644")
        d = f.to_dict()
        assert d["filepath"] == "/tmp/a.txt"
        assert d["name"] == "a.txt"
        assert d["size"] == 10
        assert d["sha256sum"] == "ab" * 32
        assert d["permissions"] == "644"
        assert d["ctime"] is None
        assert d["mtime"] is None


class TestFileSha256Cache:
    def test_clear_cache_does_not_raise(self):
        clear_sha256_cache()

    def test_invalidate_nonexistent_does_not_raise(self):
        invalidate_sha256_cache("/nonexistent/path.txt")

    def test_sha256_cache_max_size_constant(self):
        """sha256_cache_MAX_SIZE must be a positive integer."""
        assert isinstance(SHA256_CACHE_MAX_SIZE, int)
        assert SHA256_CACHE_MAX_SIZE > 0

    def test_cache_evicts_oldest_when_full(self):
        """Inserting beyond sha256_cache_MAX_SIZE evicts the LRU entry."""
        clear_sha256_cache()
        # Fill the cache to the limit using fake paths
        for i in range(SHA256_CACHE_MAX_SIZE):
            _set_cached_sha256(f"/fake/path/{i}.txt", "a" * 32, i, 0, 0)
        assert len(_sha256_cache) == SHA256_CACHE_MAX_SIZE

        # Adding one more entry should evict the oldest (/fake/path/0.txt)
        _set_cached_sha256("/fake/path/overflow.txt", "b" * 32, 9999, 0, 0)
        assert len(_sha256_cache) == SHA256_CACHE_MAX_SIZE
        assert "/fake/path/0.txt" not in _sha256_cache
        assert "/fake/path/overflow.txt" in _sha256_cache

        clear_sha256_cache()  # clean up for subsequent tests

    def test_cache_hit_returns_value_and_moves_to_end(self):
        """A hit with matching identity returns the cached sum and refreshes LRU order."""
        clear_sha256_cache()
        _set_cached_sha256("/a.txt", "a" * 64, mtime_ns=10, ctime_ns=100, size=5)
        _set_cached_sha256("/b.txt", "b" * 64, mtime_ns=20, ctime_ns=200, size=5)
        # Hitting the oldest entry should move it to the end (most-recent).
        assert _get_cached_sha256("/a.txt", 10, 100, 5) == "a" * 64
        assert next(reversed(_sha256_cache)) == "/a.txt"
        clear_sha256_cache()

    def test_cache_miss_on_mtime_change_evicts_entry(self):
        """A stale mtime drops the entry and returns None."""
        clear_sha256_cache()
        _set_cached_sha256("/c.txt", "c" * 64, mtime_ns=10, ctime_ns=100, size=5)
        assert _get_cached_sha256("/c.txt", 11, 100, 5) is None
        assert "/c.txt" not in _sha256_cache
        clear_sha256_cache()

    def test_cache_miss_on_size_change_evicts_entry(self):
        """A changed size must drop the stale digest instead of serving it."""
        clear_sha256_cache()
        _set_cached_sha256("/d.txt", "d" * 64, mtime_ns=10, ctime_ns=100, size=5)
        assert _get_cached_sha256("/d.txt", 10, 100, 6) is None
        assert "/d.txt" not in _sha256_cache
        clear_sha256_cache()

    def test_cache_miss_on_ctime_change_evicts_entry(self):
        """A same-mtime same-size rewrite must still miss via ctime.

        Regression for the cross-cycle reuse: the old identity (seconds-granularity
        mtime + size) could serve a stale digest after a same-second rewrite with
        identical size. ctime changes on every write with kernel resolution, so it
        is part of the identity and a stale hit is impossible.
        """
        clear_sha256_cache()
        _set_cached_sha256("/e.txt", "e" * 64, mtime_ns=10, ctime_ns=100, size=5)
        assert _get_cached_sha256("/e.txt", 10, 101, 5) is None
        assert "/e.txt" not in _sha256_cache
        clear_sha256_cache()

    def test_cache_miss_on_unknown_path(self):
        clear_sha256_cache()
        assert _get_cached_sha256("/never-seen.txt", 1, 1, 0) is None


class TestFileGetSha256Cache:
    """``File.get`` reuses the digest when the stat identity is unchanged.

    These tests pin the cross-cycle cache contract: an untouched file must be
    hashed once and served from cache on every later ``File.get``, while any
    rewrite — including one that restores mtime and size — must re-hash.
    """

    def test_unchanged_file_serves_cached_digest(self, tmp_path):
        from hsync_common.models.file import _sha256_cache as cache

        clear_sha256_cache()
        target = tmp_path / "stable.txt"
        target.write_bytes(b"stable content")

        first = File.get(str(target))
        assert first is not None
        cached_sum = first.sha256sum
        # Second get: served from cache (identity unchanged).
        second = File.get(str(target))
        assert second is not None and second.sha256sum == cached_sum
        assert str(target) in cache

        # Rewrite with the same size but different content: mtime/ctime change.
        target.write_bytes(b"STABLE CONTENT")
        third = File.get(str(target))
        assert third is not None
        assert third.sha256sum != cached_sum
        assert third.sha256sum is not None
        clear_sha256_cache()

    def test_same_size_rewrite_rehashes(self, tmp_path):
        """Same-size rewrite (even mtime-restored) must never serve the old digest."""
        clear_sha256_cache()
        target = tmp_path / "rewrite.txt"
        target.write_bytes(b"AAAAAAAA")
        first = File.get(str(target))
        assert first is not None
        old_sum = first.sha256sum

        # Restore mtime (touch -r style) so only ctime moves: the identity
        # still changes and the digest must be recomputed.
        import os

        mtime_ns = os.stat(target).st_mtime_ns
        target.write_bytes(b"BBBBBBBB")
        os.utime(target, ns=(os.stat(target).st_atime_ns, mtime_ns))

        second = File.get(str(target))
        assert second is not None
        assert second.sha256sum != old_sum
        clear_sha256_cache()


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

    def test_get_stat_failure_degrades_to_none(self, monkeypatch):
        """Regression: a file that vanishes between exists()/stat() and the
        hash read (TOCTOU with the watcher/transfers sharing the bucket) must
        degrade to None, never abort the sync scan with an OSError."""
        import hsync_common.models.file as file_mod

        def _boom(_path):
            raise OSError("vanished")

        monkeypatch.setattr(file_mod.os, "stat", _boom)
        assert File.get("/tmp/whatever.txt") is None


class TestFileFromDict:
    def test_from_dict_with_strip(self):
        d = {"filepath": "/base/subdir/file.txt", "size": 50}
        f = File.from_dict(d, dir_prefix="/base", strip_dir_prefix=True)
        assert f.filepath == "subdir/file.txt"

    def test_from_dict_relative_with_strip_is_verbatim(self):
        """A bucket-relative wire path with ``strip_dir_prefix=True`` is already
        relative: the prefix never applies and the path is kept verbatim (the
        production shape — server/master listings are bucket-relative)."""
        f = File.from_dict(
            {"filepath": "subdir/file.txt", "size": 50}, dir_prefix="/base", strip_dir_prefix=True
        )
        assert f.filepath == "subdir/file.txt"

    def test_from_dict_without_strip(self):
        d = {"filepath": "subdir/file.txt", "size": 50}
        f = File.from_dict(d, dir_prefix="/base", strip_dir_prefix=False)
        assert "/base" in f.filepath  # type: ignore[reportOperatorIssue]

    def test_prepend_matches_pathlib_join(self):
        """Pin the prepend fast-path contract: for normalized inputs the string
        concat must equal ``str(Path(prefix) / rel)`` exactly."""
        from pathlib import Path as _Path

        for prefix, rel in [
            ("/base", "subdir/file.txt"),
            ("/base/", "subdir/file.txt"),
            ("/srv/hsync/buckets/media", "photos/2024/album/photo-001.jpg"),
            ("/base", "/subdir/file.txt"),
        ]:
            f = File.from_dict(
                {"filepath": rel, "size": 1}, dir_prefix=prefix, strip_dir_prefix=False
            )
            expected = str(_Path(prefix) / str(rel).lstrip("/"))
            assert f.filepath == expected  # type: ignore[reportOperatorIssue]

    def test_from_dict_raises_if_strip_without_prefix(self):
        d = {"filepath": "/base/file.txt", "size": 10}
        with pytest.raises(ValueError):
            File.from_dict(d, dir_prefix=None, strip_dir_prefix=True)

    def test_from_dict_no_prefix_keeps_filepath(self):
        f = File.from_dict({"filepath": "plain.txt", "size": 1}, strip_dir_prefix=False)
        assert f.filepath == "plain.txt"

    def test_from_dict_sibling_prefix_is_not_mangled(self):
        """Regression: a path sharing only the string prefix of the bucket is
        NOT inside it. Component-aware stripping keeps it verbatim instead of
        producing a bogus relative path ("2/x")."""
        f = File.from_dict(
            {"filepath": "/base2/x.txt", "size": 1}, dir_prefix="/base", strip_dir_prefix=True
        )
        assert f.filepath == "/base2/x.txt"  # type: ignore[reportOperatorIssue]
