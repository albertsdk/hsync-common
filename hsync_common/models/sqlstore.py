# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Shared SQLite backend for causal version and tombstone persistence.

One installation-level database (``syncstate.db``) holds every folder's
versions and tombstones, keyed by ``folder_id`` (ADR-0025). Connections use
autocommit; callers wrap a sync-cycle flush in :meth:`StateDb.begin_immediate`
/ :meth:`StateDb.commit`. WAL is preferred; filesystems that reject it fall
back to ``DELETE`` journal mode.

Consumers: ``hsync-common`` (``SyncStateStore``, ``TombstoneStore``),
``hsync-client`` and ``hsync-server`` (shared DB handle per installation).
Android mirrors the schema in ``SQLiteOpenHelper``, not this module.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

__all__ = [
    "RETAIN_CHUNK_SIZE",
    "SCHEMA_USER_VERSION",
    "StateDb",
    "get_state_db",
    "open_state_db",
    "reset_state_db_cache",
]

_db_cache: dict[str, StateDb] = {}

SCHEMA_USER_VERSION = 1

# SQLite default parameter limit is 999; stay well under it for ``IN`` clauses
# used as a fallback. The primary ``retain`` path uses a temp-table anti-join.
RETAIN_CHUNK_SIZE = 500

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS folders (
  folder_id      TEXT PRIMARY KEY,
  canonical_path TEXT NOT NULL,
  created_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS buckets (
  bucket_name TEXT PRIMARY KEY,
  folder_id   TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS versions (
  folder_id TEXT NOT NULL REFERENCES folders(folder_id) ON DELETE CASCADE,
  key       TEXT NOT NULL,
  base_hash TEXT NOT NULL,
  version_id TEXT NOT NULL,
  origin_cid TEXT,
  ts        REAL NOT NULL,
  vclock    TEXT NOT NULL,
  corrected_mtime REAL,
  PRIMARY KEY (folder_id, key)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS tombstones (
  folder_id  TEXT NOT NULL REFERENCES folders(folder_id) ON DELETE CASCADE,
  key        TEXT NOT NULL,
  sha256sum  TEXT,
  version_id TEXT NOT NULL,
  origin_cid TEXT,
  ts         REAL NOT NULL,
  vclock     TEXT NOT NULL,
  PRIMARY KEY (folder_id, key)
) WITHOUT ROWID;
"""


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply the ADR-0025 PRAGMA set; fall back from WAL to DELETE if needed."""
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=FULL")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        mode = conn.execute("PRAGMA journal_mode").fetchone()
        if mode is None or str(mode[0]).lower() != "wal":
            conn.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error:
        conn.execute("PRAGMA journal_mode=DELETE")


def open_state_db(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the installation DB with ADR-0025 PRAGMAs and schema.

    Consumers: :class:`StateDb` and tests that need a raw connection.
    """
    if str(db_path) == ":memory:":
        conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    conn.executescript(_SCHEMA_SQL)
    conn.execute(f"PRAGMA user_version={SCHEMA_USER_VERSION}")
    return conn


def get_state_db(db_path: str | Path) -> StateDb:
    """Return a cached :class:`StateDb` for *db_path* (one connection per file).

    ``:memory:`` is never cached: each caller gets an isolated database.
    Consumers: ``SyncStateStore``, ``TombstoneStore``, ``hsync-client`` /
    ``hsync-server`` wrappers.
    """
    if str(db_path) == ":memory:":
        return StateDb(db_path)
    key = str(Path(db_path).resolve())
    db = _db_cache.get(key)
    if db is None:
        db = StateDb(db_path)
        _db_cache[key] = db
    return db


def reset_state_db_cache() -> None:
    """Close and drop every cached connection (tests; process teardown)."""
    for db in _db_cache.values():
        try:
            db.close()
        except sqlite3.Error:
            pass
    _db_cache.clear()


class StateDb:
    """Thin wrapper around a shared ``syncstate.db`` connection.

    One instance is typically cached per ``db_path``. Folder rows are
    ensured on first use. Consumers: ``SyncStateStore``, ``TombstoneStore``.
    """

    def __init__(self, db_path: str | Path, conn: sqlite3.Connection | None = None):
        self.db_path = Path(db_path)
        self._conn = conn if conn is not None else open_state_db(self.db_path)

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def begin_immediate(self) -> None:
        """Start a reserved write transaction (one per sync-cycle flush)."""
        self._conn.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        """Commit the current transaction."""
        self._conn.execute("COMMIT")

    def rollback(self) -> None:
        """Roll back the current transaction, ignoring 'no transaction'."""
        try:
            self._conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    def ensure_folder(self, folder_id: str, canonical_path: str = "") -> None:
        """Insert the ``folders`` row if missing; refresh ``canonical_path``."""
        now = int(time.time())
        self._conn.execute(
            """
            INSERT INTO folders (folder_id, canonical_path, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(folder_id) DO UPDATE SET
              canonical_path = CASE
                WHEN excluded.canonical_path = '' THEN folders.canonical_path
                ELSE excluded.canonical_path
              END
            """,
            (folder_id, canonical_path, now),
        )

    def folder_canonical_path(self, folder_id: str) -> str | None:
        """Return the stored canonical path for *folder_id*, if any."""
        row = self._conn.execute(
            "SELECT canonical_path FROM folders WHERE folder_id = ?",
            (folder_id,),
        ).fetchone()
        return None if row is None else str(row["canonical_path"])

    def find_folder_by_path(self, canonical_path: str) -> str | None:
        """Return the folder_id registered for *canonical_path*, if any."""
        row = self._conn.execute(
            "SELECT folder_id FROM folders WHERE canonical_path = ?",
            (canonical_path,),
        ).fetchone()
        return None if row is None else str(row["folder_id"])

    def ensure_bucket_id(self, bucket_name: str) -> str:
        """Return the server-side folder UUID for *bucket_name*, creating one.

        Consumers: ``hsync-server`` (``versions.py`` / ``tombstones.py``).
        """
        row = self._conn.execute(
            "SELECT folder_id FROM buckets WHERE bucket_name = ?",
            (bucket_name,),
        ).fetchone()
        if row is not None:
            return str(row["folder_id"])
        import uuid

        folder_id = str(uuid.uuid4())
        self.ensure_folder(folder_id, canonical_path=f"bucket:{bucket_name}")
        self._conn.execute(
            "INSERT INTO buckets (bucket_name, folder_id) VALUES (?, ?)",
            (bucket_name, folder_id),
        )
        return folder_id

    # ── versions ────────────────────────────────────────────────────
    def upsert_version(
        self,
        folder_id: str,
        key: str,
        *,
        base_hash: str,
        version_id: str,
        origin_cid: str | None,
        ts: float,
        vclock: str,
        corrected_mtime: float | None,
    ) -> None:
        """Insert or replace one version row."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO versions
              (folder_id, key, base_hash, version_id, origin_cid, ts, vclock, corrected_mtime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (folder_id, key, base_hash, version_id, origin_cid, ts, vclock, corrected_mtime),
        )

    def delete_version(self, folder_id: str, key: str) -> bool:
        """Delete one version row; return True if a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM versions WHERE folder_id = ? AND key = ?",
            (folder_id, key),
        )
        return cur.rowcount > 0

    def get_version(self, folder_id: str, key: str) -> sqlite3.Row | None:
        """Return one version row, or None."""
        return self._conn.execute(
            "SELECT * FROM versions WHERE folder_id = ? AND key = ?",
            (folder_id, key),
        ).fetchone()

    def iter_versions(self, folder_id: str) -> Iterator[sqlite3.Row]:
        """Yield every version row for *folder_id*."""
        return self._conn.execute(
            "SELECT * FROM versions WHERE folder_id = ?",
            (folder_id,),
        )

    def count_versions(self, folder_id: str) -> int:
        """Return the number of version rows for *folder_id*."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM versions WHERE folder_id = ?",
            (folder_id,),
        ).fetchone()
        return 0 if row is None else int(row["n"])

    def retain_versions(self, folder_id: str, keep: Sequence[str]) -> int:
        """Drop version rows whose key is not in *keep*; return drop count."""
        return self._retain("versions", folder_id, keep)

    # ── tombstones ──────────────────────────────────────────────────
    def upsert_tombstone(
        self,
        folder_id: str,
        key: str,
        *,
        sha256sum: str | None,
        version_id: str,
        origin_cid: str | None,
        ts: float,
        vclock: str,
    ) -> None:
        """Insert or replace one tombstone row."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO tombstones
              (folder_id, key, sha256sum, version_id, origin_cid, ts, vclock)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (folder_id, key, sha256sum, version_id, origin_cid, ts, vclock),
        )

    def delete_tombstone(self, folder_id: str, key: str) -> bool:
        """Delete one tombstone row; return True if a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM tombstones WHERE folder_id = ? AND key = ?",
            (folder_id, key),
        )
        return cur.rowcount > 0

    def get_tombstone(self, folder_id: str, key: str) -> sqlite3.Row | None:
        """Return one tombstone row, or None."""
        return self._conn.execute(
            "SELECT * FROM tombstones WHERE folder_id = ? AND key = ?",
            (folder_id, key),
        ).fetchone()

    def iter_tombstones(self, folder_id: str) -> Iterator[sqlite3.Row]:
        """Yield every tombstone row for *folder_id*."""
        return self._conn.execute(
            "SELECT * FROM tombstones WHERE folder_id = ?",
            (folder_id,),
        )

    def count_tombstones(self, folder_id: str) -> int:
        """Return the number of tombstone rows for *folder_id*."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM tombstones WHERE folder_id = ?",
            (folder_id,),
        ).fetchone()
        return 0 if row is None else int(row["n"])

    def prune_tombstones(self, folder_id: str, cutoff_ts: float) -> int:
        """Delete tombstones older than *cutoff_ts*; return drop count."""
        cur = self._conn.execute(
            "DELETE FROM tombstones WHERE folder_id = ? AND ts < ?",
            (folder_id, cutoff_ts),
        )
        return cur.rowcount

    def retain_tombstones(self, folder_id: str, keep: Sequence[str]) -> int:
        """Drop tombstone rows whose key is not in *keep*; return drop count."""
        return self._retain("tombstones", folder_id, keep)

    def _retain(self, table: str, folder_id: str, keep: Sequence[str]) -> int:
        """Temp-table anti-join retain; empty *keep* deletes every row."""
        if table not in {"versions", "tombstones"}:
            raise ValueError(f"unknown retain table: {table}")
        if not keep:
            cur = self._conn.execute(
                f"DELETE FROM {table} WHERE folder_id = ?",
                (folder_id,),
            )
            return cur.rowcount
        self._conn.execute("CREATE TEMP TABLE IF NOT EXISTS _retain_keep (key TEXT PRIMARY KEY)")
        try:
            self._conn.execute("DELETE FROM _retain_keep")
            self._conn.executemany(
                "INSERT OR IGNORE INTO _retain_keep (key) VALUES (?)",
                ((k,) for k in keep),
            )
            cur = self._conn.execute(
                f"""
                DELETE FROM {table}
                WHERE folder_id = ?
                  AND key NOT IN (SELECT key FROM _retain_keep)
                """,
                (folder_id,),
            )
            return cur.rowcount
        finally:
            self._conn.execute("DROP TABLE IF EXISTS _retain_keep")
