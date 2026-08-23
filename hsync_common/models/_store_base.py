# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Shared in-memory + SQLite plumbing for causal stores.

:class:`CausalStoreBase` owns the fields and methods that
:class:`~.version_store.SyncStateStore` and
:class:`~.tombstone_store.TombstoneStore` share: the path-keyed map, dirty
flag, cached :class:`~.sqlstore.StateDb` handle, ``clear``/``get``, and
backend resolution. Domain merge/record/load/save stay in the subclasses.

Consumers: ``hsync-common`` store classes only (not a public API).
"""

from __future__ import annotations

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
