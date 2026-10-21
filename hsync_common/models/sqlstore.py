# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Shared SQLite backend for causal version and tombstone persistence.

One SQLite database per folder (client) or per bucket (server) holds the
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
import threading
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

__all__ = [
    "INCREMENTAL_VACUUM_INTERVAL_S",
    "INCREMENTAL_VACUUM_PAGES",
    "SCHEMA_USER_VERSION",
    "StateDb",
    "get_state_db",
    "incremental_vacuum_state_db",
    "open_state_db",
    "reset_state_db_cache",
    "state_db_freelist_count",
    "vacuum_state_db",
]

_db_cache: dict[str, StateDb] = {}
# Guards cache population: two workers opening the same file concurrently must
# share one StateDb. Without it both can see an empty slot, both open a
# connection, and the overwritten one is never closed (leaked handle).
_db_cache_lock = threading.Lock()

SCHEMA_USER_VERSION = 1

# Periodic maintenance cadence for the installation DB (ADR-0025). The
# ``retain``/tombstone-TTL pruning deletes rows but, without auto-vacuum, the
# freed pages stay in the file; consumers reclaim them incrementally at this
# cadence and with a full VACUUM at process boundaries. Consumers:
# ``hsync-client`` (end of sync cycle) and ``hsync-server`` (background task).
INCREMENTAL_VACUUM_INTERVAL_S = 3600.0
INCREMENTAL_VACUUM_PAGES = 1000

# Keys per DELETE statement. Bounded so a large prune cannot exceed SQLite's
# statement-variable limit.
_DELETE_KEYS_CHUNK = 500

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS folders (
  folder_id      TEXT PRIMARY KEY,
  canonical_path TEXT NOT NULL,
  created_at     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_folders_canonical_path ON folders(canonical_path);

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
    # INCREMENTAL auto-vacuum keeps the file compact as rows are pruned (the
    # retain/tombstone-TTL deletes free pages that would otherwise linger in
    # the file forever). The mode is stored in the database header, so it must
    # be set BEFORE any table is created: ``open_state_db`` runs this function
    # before executing the schema. On a database that already has tables the
    # assignment is a harmless no-op (SQLite keeps the existing mode).
    conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
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
    if db is not None:
        return db
    # Double-checked under the lock: concurrent first-use must not create (and
    # then overwrite, leaking) a second connection for the same file.
    with _db_cache_lock:
        db = _db_cache.get(key)
        if db is None:
            db = StateDb(db_path)
            _db_cache[key] = db
        return db


def reset_state_db_cache() -> None:
    """Close and drop every cached connection (tests; process teardown)."""
    with _db_cache_lock:
        for db in _db_cache.values():
            try:
                db.close()
            except sqlite3.Error:
                pass
        _db_cache.clear()


def incremental_vacuum_state_db(db_path: str | Path, pages: int = INCREMENTAL_VACUUM_PAGES) -> int:
    """Reclaim up to *pages* free pages from the installation DB (best-effort).

    No-op when the file does not exist yet (never creates one). Consumers:
    ``hsync-client`` (throttled, end of sync cycle) and ``hsync-server``
    (periodic background task).
    """
    if not Path(db_path).exists():
        return 0
    return get_state_db(db_path).incremental_vacuum(pages)


def vacuum_state_db(db_path: str | Path) -> int:
    """Fully rebuild the installation DB to reclaim all free space.

    Returns the number of free pages reclaimed, or 0 when the file does not
    exist yet (never creates one). Consumers: ``hsync-client`` (graceful
    shutdown) and ``hsync-server`` (startup/shutdown).
    """
    if not Path(db_path).exists():
        return 0
    return get_state_db(db_path).vacuum()


def state_db_freelist_count(db_path: str | Path) -> int:
    """Return the number of free pages in the installation DB (0 if absent).

    Consumers: ``hsync-server`` (gate the startup VACUUM so a clean restart
    never pays a redundant full rebuild).
    """
    if not Path(db_path).exists():
        return 0
    return get_state_db(db_path).freelist_count()


class StateDb:
    """Thin wrapper around a shared ``state DB`` connection.

    One instance is typically cached per ``db_path``. Folder rows are
    ensured on first use. Access to the underlying connection is
    serialized with an instance-level lock so independent stores
    (:class:`SyncStateStore`, :class:`TombstoneStore`) that share the
    same file do not interleave statements (temp-table collision, etc.).
    Consumers: ``SyncStateStore``, ``TombstoneStore``.
    """

    def __init__(self, db_path: str | Path, conn: sqlite3.Connection | None = None):
        self.db_path = Path(db_path)
        self._conn = conn if conn is not None else open_state_db(self.db_path)
        self._lock = threading.RLock()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        """Close the underlying connection."""
        with self._lock:
            self._conn.close()

    def begin_immediate(self) -> None:
        """Start a reserved write transaction (one per sync-cycle flush)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        """Commit the current transaction."""
        with self._lock:
            self._conn.execute("COMMIT")

    def rollback(self) -> None:
        """Roll back the current transaction, ignoring 'no transaction'."""
        with self._lock:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Yield inside a reserved write transaction.

        Opens ``BEGIN IMMEDIATE``; when a transaction is already open (a
        nested flush inside a caller-held transaction) the resulting
        ``sqlite3.OperationalError`` is tolerated and the caller's transaction
        is used as-is. Commits on clean exit, rolls back on error.

        Consumers: ``SyncStateStore.save``, ``TombstoneStore.save``.
        """
        with self._lock:
            own_txn = False
            try:
                self.begin_immediate()
                own_txn = True
            except sqlite3.OperationalError:
                own_txn = False
            try:
                yield
                if own_txn:
                    self.commit()
            except Exception:
                if own_txn:
                    self.rollback()
                raise

    def ensure_folder(self, folder_id: str, canonical_path: str = "") -> None:
        """Insert the ``folders`` row if missing; refresh ``canonical_path``."""
        with self._lock:
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
        with self._lock:
            row = self._conn.execute(
                "SELECT canonical_path FROM folders WHERE folder_id = ?",
                (folder_id,),
            ).fetchone()
            return None if row is None else str(row["canonical_path"])

    def find_folder_by_path(self, canonical_path: str) -> str | None:
        """Return the folder_id registered for *canonical_path*, if any."""
        with self._lock:
            row = self._conn.execute(
                "SELECT folder_id FROM folders WHERE canonical_path = ?",
                (canonical_path,),
            ).fetchone()
            return None if row is None else str(row["folder_id"])

    def ensure_bucket_id(self, bucket_name: str) -> str:
        """Return the server-side folder UUID for *bucket_name*, creating one.

        Consumers: ``hsync-server`` (``versions.py`` / ``tombstones.py``).
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT folder_id FROM buckets WHERE bucket_name = ?",
                (bucket_name,),
            ).fetchone()
            if row is not None:
                return str(row["folder_id"])
            folder_id = str(uuid.uuid4())
            self.ensure_folder(folder_id, canonical_path=f"bucket:{bucket_name}")
            self._conn.execute(
                "INSERT INTO buckets (bucket_name, folder_id) VALUES (?, ?)",
                (bucket_name, folder_id),
            )
            return folder_id

    # ── maintenance ─────────────────────────────────────────────────
    def freelist_count(self) -> int:
        """Return the number of free pages in the database file.

        A proxy for how much space a VACUUM (or ``incremental_vacuum``) would
        reclaim; consumers use it to skip a full rebuild when there is nothing
        meaningful to reclaim.
        """
        with self._lock:
            row = self._conn.execute("PRAGMA freelist_count").fetchone()
            return int(row[0]) if row is not None else 0

    def incremental_vacuum(self, pages: int) -> int:
        """Reclaim up to *pages* free pages in place; return the freed count.

        A no-op (returns 0) when ``pages <= 0``, on a database not created with
        ``auto_vacuum=INCREMENTAL``, or with no free pages. The per-call bound
        keeps a periodic invocation lightweight (ADR-0025).
        """
        pages = int(pages)
        if pages <= 0:
            return 0
        with self._lock:
            before = self.freelist_count()
            self._conn.execute(f"PRAGMA incremental_vacuum({pages})")
            return max(0, before - self.freelist_count())

    def vacuum(self) -> int:
        """Rebuild the database file, reclaiming all free space.

        Returns the number of free pages reclaimed. Runs in autocommit (the
        connection never wraps a surrounding transaction) and requires that no
        other connection holds an active transaction, so callers invoke it at
        a process boundary (startup/shutdown) where no statement is in flight.
        """
        with self._lock:
            before = self.freelist_count()
            self._conn.execute("VACUUM")
            return max(0, before - self.freelist_count())

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
        with self._lock:
            self._conn.execute(
                """
            INSERT OR REPLACE INTO versions
              (folder_id, key, base_hash, version_id, origin_cid, ts, vclock, corrected_mtime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (folder_id, key, base_hash, version_id, origin_cid, ts, vclock, corrected_mtime),
            )

    def iter_versions(self, folder_id: str) -> list[sqlite3.Row]:
        """Return every version row for *folder_id* as a list.

        The result set is fully consumed inside the instance lock so the
        cursor cannot outlive the critical section.
        """
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT * FROM versions WHERE folder_id = ?",
                    (folder_id,),
                )
            )

    def count_versions(self, folder_id: str) -> int:
        """Return the number of version rows for *folder_id*."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM versions WHERE folder_id = ?",
                (folder_id,),
            ).fetchone()
            return 0 if row is None else int(row["n"])

    def delete_versions(self, folder_id: str, keys: Sequence[str]) -> int:
        """Delete the given version rows; return the number actually removed."""
        with self._lock:
            return self._delete_keys("versions", folder_id, keys)

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
        with self._lock:
            self._conn.execute(
                """
            INSERT OR REPLACE INTO tombstones
              (folder_id, key, sha256sum, version_id, origin_cid, ts, vclock)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (folder_id, key, sha256sum, version_id, origin_cid, ts, vclock),
            )

    def iter_tombstones(self, folder_id: str) -> list[sqlite3.Row]:
        """Return every tombstone row for *folder_id* as a list.

        The result set is fully consumed inside the instance lock so the
        cursor cannot outlive the critical section.
        """
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT * FROM tombstones WHERE folder_id = ?",
                    (folder_id,),
                )
            )

    def delete_tombstones(self, folder_id: str, keys: Sequence[str]) -> int:
        """Delete the given tombstone rows; return the number actually removed."""
        with self._lock:
            return self._delete_keys("tombstones", folder_id, keys)

    def reset_folder(self, folder_id: str) -> tuple[int, int]:
        """Forget one folder's sync history: drop its versions and tombstones.

        The ``folders``/``buckets`` rows survive, so the folder UUID, its
        canonical path and the bucket binding stay valid and the next sync
        re-opens the same DB. Only the merge bases and the deletion markers are
        discarded, which is what makes the next cycle reconcile from scratch.
        Both deletes share one transaction: an interruption never leaves a
        half-reset folder.

        Returns:
            ``(versions_deleted, tombstones_deleted)``.

        Consumers: ``hsync-client`` (``hsync state reset``).
        """
        with self.transaction():
            versions = self._conn.execute(
                "DELETE FROM versions WHERE folder_id = ?", (folder_id,)
            ).rowcount
            tombstones = self._conn.execute(
                "DELETE FROM tombstones WHERE folder_id = ?", (folder_id,)
            ).rowcount
        return versions, tombstones

    def _delete_keys(self, table: str, folder_id: str, keys: Sequence[str]) -> int:
        """Delete rows for *keys* in bounded chunks; return the deleted count.

        Chunked so a large prune cannot exceed SQLite's statement-variable cap.
        Callers hold :attr:`_lock`.
        """
        if table not in {"versions", "tombstones"}:
            raise ValueError(f"unknown table: {table}")
        deleted = 0
        key_list = list(keys)
        for start in range(0, len(key_list), _DELETE_KEYS_CHUNK):
            chunk = key_list[start : start + _DELETE_KEYS_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            cur = self._conn.execute(
                f"DELETE FROM {table} WHERE folder_id = ? AND key IN ({placeholders})",
                (folder_id, *chunk),
            )
            deleted += cur.rowcount
        return deleted
