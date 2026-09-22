# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Shared in-memory + SQLite plumbing for causal stores.

:class:`CausalStoreBase` owns the fields and methods that
:class:`~.version_store.SyncStateStore` and
:class:`~.tombstone_store.TombstoneStore` share: the path-keyed map, dirty
tracking, cached :class:`~.sqlstore.StateDb` handle, ``clear``/``get``, backend
resolution, and the generic ``load``/``save`` persistence skeleton. The
subclasses supply only the per-table hooks (``_iter_rows``, ``_parse_row``,
``_delete_rows``, ``_upsert_row``, ``_max_entries``) plus their domain
merge/record logic.

Persistence is **incremental**: every mutation marks only the affected key
(upsert or delete) and :meth:`save` writes just those rows. Rewriting the whole
map on every save made the server's per-upload save O(N) — a full sync of N
files then cost O(N²) writes and its temp-table retain raised
``database table is locked`` under concurrent uploads. Durability is unchanged:
the same transaction and ``PRAGMA synchronous=FULL`` still apply.

Consumers: ``hsync-common`` store classes only (not a public API).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from ._util import tombstone_key
from .sqlstore import StateDb, get_state_db


class CausalStoreBase[T]:
    """In-memory path→entry map with a lazily opened installation DB handle."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        folder_id: str | None = None,
        *,
        canonical_path: str = "",
    ) -> None:
        self.db_path = str(db_path) if db_path is not None else None
        self.folder_id = folder_id
        self.canonical_path = canonical_path
        self._data: dict[str, T] = {}
        self._db: StateDb | None = None
        self._dirty = False
        self._dirty_keys: set[str] = set()
        self._deleted_keys: set[str] = set()

    def clear(self, relpath: str) -> bool:
        """Drop the stored entry for a relative path; return True if it existed."""
        key = tombstone_key(relpath)
        dropped = self._data.pop(key, None) is not None
        if dropped:
            self._mark_deleted(key)
        return dropped

    def get(self, relpath: str) -> T | None:
        """Return the stored entry for a relative path, if any."""
        return self._data.get(tombstone_key(relpath))

    def __len__(self) -> int:
        return len(self._data)

    def _backend(self) -> StateDb | None:
        """Return the shared DB handle when ``db_path`` + ``folder_id`` are set."""
        if not self.db_path or not self.folder_id:
            return None
        if self._db is None:
            self._db = get_state_db(self.db_path)
        return self._db

    # ── dirty tracking ──────────────────────────────────────────────
    def _mark_dirty(self, key: str) -> None:
        """Record that *key*'s current value must be upserted on next save."""
        self._dirty_keys.add(key)
        self._deleted_keys.discard(key)
        self._dirty = True

    def _mark_deleted(self, key: str) -> None:
        """Record that *key*'s row must be deleted on next save."""
        self._deleted_keys.add(key)
        self._dirty_keys.discard(key)
        self._dirty = True

    # ── persistence hooks (overridden by each store) ────────────────
    # ``load``/``save`` are implemented once here; the subclasses only supply
    # the per-table primitives below, so the two stores cannot drift apart in
    # their persistence skeleton (backend guard, ensure_folder, transaction,
    # incremental delete-then-upsert, dirty reset).

    def _max_entries(self) -> int | None:
        """Optional cap on entries loaded from the DB (None = unlimited)."""
        return None

    def _iter_rows(self, db: StateDb, folder_id: str) -> list[sqlite3.Row]:
        """Return the raw DB rows for *folder_id*."""
        raise NotImplementedError

    def _parse_row(self, row: sqlite3.Row, now: int) -> tuple[str, T] | None:
        """Parse one DB row into a ``(key, entry)`` pair, or ``None`` if unusable."""
        raise NotImplementedError

    def _delete_rows(self, db: StateDb, folder_id: str, keys: list[str]) -> int:
        """Delete the rows for *keys*; return the deleted count."""
        raise NotImplementedError

    def _upsert_row(self, db: StateDb, folder_id: str, key: str, entry: T) -> None:
        """Insert or replace the DB row for ``(folder_id, key)``."""
        raise NotImplementedError

    # ── persistence ─────────────────────────────────────────────────
    def load(self) -> None:
        """Load entries from the installation DB, if configured.

        Rows that fail structural validation are dropped entry-by-entry: a
        corrupted store degrades safely without crashing startup. The optional
        per-store cap (``_max_entries``) bounds how many entries are kept.
        """
        db = self._backend()
        if db is None or self.folder_id is None:
            return
        db.ensure_folder(self.folder_id, self.canonical_path)
        cap = self._max_entries()
        now = int(time.time())
        data: dict[str, T] = {}
        excluded: set[str] = set()
        for row in self._iter_rows(db, self.folder_id):
            raw_key = str(row["key"])
            if cap is not None and len(data) >= cap:
                # Keep enumerating so excess rows can be pruned below.
                excluded.add(raw_key)
                continue
            parsed = self._parse_row(row, now)
            if parsed is None:
                excluded.add(raw_key)
                continue
            key, entry = parsed
            data[key] = entry
        self._data = data
        self._dirty = False
        self._dirty_keys.clear()
        self._deleted_keys.clear()
        # Rows deliberately excluded (structurally invalid, or beyond the cap)
        # must not survive: the old full-rewrite save pruned them, so the
        # incremental save has to mark them explicitly or the table would grow
        # unbounded and reload arbitrary subsets.
        for key in excluded - data.keys():
            self._mark_deleted(key)

    def save(self) -> None:
        """Persist pending changes to the installation DB (one transaction).

        Writes only the keys marked dirty/deleted since the last save (see
        :meth:`_mark_dirty` / :meth:`_mark_deleted`), so a store with N entries
        no longer rewrites all N rows per mutation. No-op when nothing changed
        or there is no backend. Callers that already hold a ``BEGIN IMMEDIATE``
        (client ``flush``) still get a consistent snapshot: the transaction
        context opens its own only when none is active.
        """
        db = self._backend()
        if db is None or self.folder_id is None or not self._dirty:
            return
        db.ensure_folder(self.folder_id, self.canonical_path)
        deleted = sorted(self._deleted_keys)
        upserts = sorted(self._dirty_keys)
        with db.transaction():
            if deleted:
                self._delete_rows(db, self.folder_id, deleted)
            for key in upserts:
                entry = self._data.get(key)
                if entry is not None:
                    self._upsert_row(db, self.folder_id, key, entry)
        self._dirty = False
        self._dirty_keys.clear()
        self._deleted_keys.clear()
