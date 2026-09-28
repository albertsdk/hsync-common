"""Tests for the shared SQLite state backend (ADR-0025)."""

import sqlite3

from hsync_common.models.sqlstore import (
    SCHEMA_USER_VERSION,
    StateDb,
    get_state_db,
    incremental_vacuum_state_db,
    open_state_db,
    reset_state_db_cache,
    state_db_freelist_count,
    vacuum_state_db,
)


class TestOpenStateDb:
    def test_creates_schema_and_wal(self, tmp_path):
        conn = open_state_db(tmp_path / "state DB")
        try:
            tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert {"folders", "buckets", "versions", "tombstones"} <= tables
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_USER_VERSION
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert str(mode).lower() == "wal"
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            conn.close()

    def test_wal_failure_falls_back_to_delete(self, tmp_path, monkeypatch):
        real_connect = sqlite3.connect

        class _Conn:
            def __init__(self, inner):
                self._inner = inner

            def execute(self, sql, *args, **kwargs):
                if "journal_mode=WAL" in sql.replace(" ", ""):
                    raise sqlite3.Error("wal unsupported")
                return self._inner.execute(sql, *args, **kwargs)

            def executescript(self, sql):
                return self._inner.executescript(sql)

            def close(self):
                return self._inner.close()

            def __getattr__(self, name):
                return getattr(self._inner, name)

        def _connect(path, **kwargs):
            return _Conn(real_connect(path, **kwargs))

        monkeypatch.setattr(sqlite3, "connect", _connect)
        conn = open_state_db(tmp_path / "state DB")
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert str(mode).lower() == "delete"
        finally:
            conn.close()


class TestStateDb:
    def test_ensure_folder_and_bucket(self, tmp_path):
        db = StateDb(tmp_path / "state DB")
        db.ensure_folder("11111111-1111-4111-8111-111111111111", "/bucket")
        assert db.folder_canonical_path("11111111-1111-4111-8111-111111111111") == "/bucket"
        assert db.find_folder_by_path("/bucket") == "11111111-1111-4111-8111-111111111111"
        first = db.ensure_bucket_id("photos")
        second = db.ensure_bucket_id("photos")
        assert first == second
        assert db.folder_canonical_path(first) == "bucket:photos"

    def test_delete_versions_chunked(self, tmp_path):
        db = StateDb(tmp_path / "state DB")
        folder_id = "11111111-1111-4111-8111-111111111111"
        db.ensure_folder(folder_id, "/b")
        for i in range(1200):
            db.upsert_version(
                folder_id,
                f"k{i}",
                base_hash="h",
                version_id="v",
                origin_cid=None,
                ts=1.0,
                vclock="{}",
                corrected_mtime=0.0,
            )
        # 1100 keys spans more than one internal chunk (limit 500).
        deleted = db.delete_versions(folder_id, [f"k{i}" for i in range(100, 1200)])
        assert deleted == 1100
        assert db.count_versions(folder_id) == 100

    def test_get_state_db_caches_file_not_memory(self, tmp_path):
        path = tmp_path / "state DB"
        a = get_state_db(path)
        b = get_state_db(path)
        assert a is b
        mem_a = get_state_db(":memory:")
        mem_b = get_state_db(":memory:")
        assert mem_a is not mem_b
        reset_state_db_cache()


class TestStateDbMaintenance:
    def _fill_and_prune(self, db: StateDb, folder_id: str, n: int = 1200) -> None:
        db.ensure_folder(folder_id, "/b")
        for i in range(n):
            db.upsert_version(
                folder_id,
                f"k{i}",
                base_hash="h",
                version_id="v",
                origin_cid=None,
                ts=1.0,
                vclock="{}",
                corrected_mtime=0.0,
            )
        # Delete all but 100 rows -> leaves free pages in the file.
        db.delete_versions(folder_id, [f"k{i}" for i in range(100, n)])

    def test_fresh_db_is_incremental_auto_vacuum(self, tmp_path):
        conn = open_state_db(tmp_path / "state DB")
        try:
            assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
        finally:
            conn.close()

    def test_incremental_vacuum_reclaims_freelist(self, tmp_path):
        db = StateDb(tmp_path / "state DB")
        folder_id = "11111111-1111-4111-8111-111111111111"
        self._fill_and_prune(db, folder_id)
        freelist_before = db.conn.execute("PRAGMA freelist_count").fetchone()[0]
        assert freelist_before > 0
        freed = db.incremental_vacuum(1000)
        assert freed > 0
        freelist_after = db.conn.execute("PRAGMA freelist_count").fetchone()[0]
        assert freelist_after < freelist_before

    def test_vacuum_clears_freelist(self, tmp_path):
        db = StateDb(tmp_path / "state DB")
        folder_id = "11111111-1111-4111-8111-111111111111"
        self._fill_and_prune(db, folder_id)
        assert db.conn.execute("PRAGMA freelist_count").fetchone()[0] > 0
        db.vacuum()
        assert db.conn.execute("PRAGMA freelist_count").fetchone()[0] == 0

    def test_module_helpers_skip_missing_file(self, tmp_path):
        missing = tmp_path / "nested" / "state DB"
        assert incremental_vacuum_state_db(missing) == 0
        vacuum_state_db(missing)  # no-op, no exception
        assert not missing.exists()

    def test_module_helpers_operate_on_existing_file(self, tmp_path):
        db = StateDb(tmp_path / "state DB")
        folder_id = "11111111-1111-4111-8111-111111111111"
        self._fill_and_prune(db, folder_id)
        freed = incremental_vacuum_state_db(db.db_path, pages=1000)
        assert freed > 0
        vacuum_state_db(db.db_path)
        assert db.conn.execute("PRAGMA freelist_count").fetchone()[0] == 0
        reset_state_db_cache()

    def test_incremental_vacuum_nonpositive_is_noop(self, tmp_path):
        db = StateDb(tmp_path / "state DB")
        folder_id = "11111111-1111-4111-8111-111111111111"
        self._fill_and_prune(db, folder_id)
        freelist = db.freelist_count()
        assert freelist > 0
        assert db.incremental_vacuum(0) == 0
        assert db.incremental_vacuum(-5) == 0
        assert db.freelist_count() == freelist

    def test_state_db_freelist_count_guard_missing_file(self, tmp_path):
        assert state_db_freelist_count(tmp_path / "missing" / "state DB") == 0
