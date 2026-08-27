# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Shared in-memory + SQLite plumbing for causal stores.

:class:`CausalStoreBase` owns the fields and methods that
:class:`~.version_store.SyncStateStore` and
:class:`~.tombstone_store.TombstoneStore` share: the path-keyed map, dirty
flag, cached :class:`~.sqlstore.StateDb` handle, ``clear``/``get``, backend
resolution, and the generic ``load``/``save`` persistence skeleton. The
subclasses supply only the per-table hooks (``_iter_rows``, ``_parse_row``,
``_retain_rows``, ``_upsert_row``, ``_max_entries``) plus their domain
merge/record logic.

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

    def clear(self, relpath: str) -> bool:
        """Drop the stored entry for a relative path; return True if it existed."""
        dropped = self._data.pop(tombstone_key(relpath), None) is not None
        if dropped:
            self._dirty = True
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

    # ── persistence hooks (overridden by each store) ────────────────
    # ``load``/``save`` are implemented once here; the subclasses only supply
    # the per-table primitives below, so the two stores cannot drift apart in
    # their persistence skeleton (backend guard, ensure_folder, transaction,
    # retain-then-upsert, dirty reset).

    def _max_entries(self) -> int | None:
        """Optional cap on entries loaded from the DB (None = unlimited)."""
        return None

    def _iter_rows(self, db: StateDb, folder_id: str) -> list[sqlite3.Row]:
        """Return the raw DB rows for *folder_id*."""
        raise NotImplementedError

    def _parse_row(self, row: sqlite3.Row, now: int) -> tuple[str, T] | None:
        """Parse one DB row into a ``(key, entry)`` pair, or ``None`` if unusable."""
        raise NotImplementedError

    def _retain_rows(self, db: StateDb, folder_id: str, keep: list[str]) -> int:
        """Delete rows whose key is not in *keep*; return the drop count."""
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
        for row in self._iter_rows(db, self.folder_id):
            if cap is not None and len(data) >= cap:
                break
            parsed = self._parse_row(row, now)
            if parsed is None:
                continue
            key, entry = parsed
            data[key] = entry
        self._data = data
        self._dirty = False

    def save(self) -> None:
        """Persist entries to the installation DB (one transaction).

        No-op when the store is not dirty or has no backend. Callers that
        already hold a ``BEGIN IMMEDIATE`` (client ``flush``) still get a
        consistent snapshot: the transaction context opens its own only when
        none is active.
        """
        db = self._backend()
        if db is None or self.folder_id is None or not self._dirty:
            return
        db.ensure_folder(self.folder_id, self.canonical_path)
        with db.transaction():
            self._retain_rows(db, self.folder_id, list(self._data.keys()))
            for key, entry in self._data.items():
                self._upsert_row(db, self.folder_id, key, entry)
        self._dirty = False
