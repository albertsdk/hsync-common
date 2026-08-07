"""Tests for the shared SQLite state backend (ADR-0025)."""

import sqlite3

from hsync_common.models.sqlstore import (
    SCHEMA_USER_VERSION,
    StateDb,
    get_state_db,
    open_state_db,
    reset_state_db_cache,
)


class TestOpenStateDb:
    def test_creates_schema_and_wal(self, tmp_path):
        conn = open_state_db(tmp_path / "syncstate.db")
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
        conn = open_state_db(tmp_path / "syncstate.db")
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert str(mode).lower() == "delete"
        finally:
            conn.close()


class TestStateDb:
    def test_ensure_folder_and_bucket(self, tmp_path):
        db = StateDb(tmp_path / "syncstate.db")
        db.ensure_folder("11111111-1111-4111-8111-111111111111", "/bucket")
        assert db.folder_canonical_path("11111111-1111-4111-8111-111111111111") == "/bucket"
        assert db.find_folder_by_path("/bucket") == "11111111-1111-4111-8111-111111111111"
        first = db.ensure_bucket_id("photos")
        second = db.ensure_bucket_id("photos")
        assert first == second
        assert db.folder_canonical_path(first) == "bucket:photos"

    def test_retain_versions_temp_table(self, tmp_path):
        db = StateDb(tmp_path / "syncstate.db")
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
        keep = [f"k{i}" for i in range(1100)]
        dropped = db.retain_versions(folder_id, keep)
        assert dropped == 100
        assert db.count_versions(folder_id) == 1100

    def test_get_state_db_caches_file_not_memory(self, tmp_path):
        path = tmp_path / "syncstate.db"
        a = get_state_db(path)
        b = get_state_db(path)
        assert a is b
        mem_a = get_state_db(":memory:")
        mem_b = get_state_db(":memory:")
        assert mem_a is not mem_b
        reset_state_db_cache()
