# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
SQLite-backed persistence for causal deletion markers (:class:`TombstoneStore`).

The causal merge logic itself (:func:`~.tombstone.tombstone_merge_decision` and
the strict payload validation) lives in :mod:`.tombstone`; this module owns only
the storage layer: an in-memory tombstone map persisted in the installation
SQLite database (``syncstate.db``, ADR-0025), keyed by a folder UUID.

Consumers: ``hsync-server`` / ``hsync-client`` (``tombstones.py`` wrappers and
gossip endpoints), ``hsync-android`` (``Tombstones.kt`` mirror). Re-exported
from :mod:`.tombstone` for the historic import path.
"""

import sqlite3
import time
from pathlib import Path

from . import tombstone
from ._store_base import CausalStoreBase
from ._util import _parse_stored_vclock, _vclock_to_json, tombstone_key
from .sqlstore import StateDb
from .tombstone import (
    TOMBSTONE_TTL_DAYS_DEFAULT,
    TombstoneEntry,
    _sanitize_entry,
    tombstone_merge_decision,
)
from .version import merge_vclocks, new_version_id, tick_vclock

__all__ = ["TombstoneStore"]


def _parse_tombstone_row(row: sqlite3.Row, now: int) -> tuple[str, TombstoneEntry] | None:
    """Sanitize a SQLite tombstone row the same way as an untrusted payload."""
    mapping = dict(row)
    key = mapping.get("key")
    entry = {
        "sha256": mapping.get("sha256sum"),
        "version_id": mapping.get("version_id", ""),
        "origin_cid": mapping.get("origin_cid"),
        "ts": mapping.get("ts", 0),
        "vclock": _parse_stored_vclock(mapping.get("vclock")),
    }
    clean = _sanitize_entry(key, entry, now)
    if clean is None or not isinstance(key, str):
        return None
    return key, clean


class TombstoneStore(CausalStoreBase[TombstoneEntry]):
    """In-memory tombstone map with SQLite persistence and causal merge."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        folder_id: str | None = None,
        *,
        ttl_days: int = TOMBSTONE_TTL_DAYS_DEFAULT,
        canonical_path: str = "",
    ):
        super().__init__(db_path, folder_id, canonical_path=canonical_path)
        self.ttl_seconds = max(0, int(ttl_days)) * 86400

    # ── mutation ────────────────────────────────────────────────────
    def record(
        self,
        relpath: str,
        sha256sum: str | None = None,
        origin_cid: str | None = None,
        prev_vclock: dict[str, int] | None = None,
        timestamp: int | float | None = None,
    ) -> None:
        """Record a deletion marker for a relative path.

        The recorded clock inherits the stored version clock for the path
        (``prev_vclock``) — merged with any existing tombstone clock — and is
        ticked by ``origin_cid``, so a subsequent delete-vs-recreate or
        delete-vs-delete resolves causally (ADR-0003). Without an origin cid
        the inherited clock is recorded un-ticked (still causally honest).
        """
        self.record_by_key(
            tombstone_key(relpath),
            sha256sum=sha256sum,
            origin_cid=origin_cid,
            prev_vclock=prev_vclock,
            timestamp=timestamp,
        )

    def record_by_key(
        self,
        key: str,
        sha256sum: str | None = None,
        origin_cid: str | None = None,
        prev_vclock: dict[str, int] | None = None,
        timestamp: int | float | None = None,
    ) -> None:
        """Record a deletion marker for an already-hashed key (causal, see ``record``)."""
        ts = int(timestamp) if timestamp is not None else int(time.time())
        existing = self._data.get(key)
        inherited = existing["vclock"] if existing else prev_vclock
        clock = merge_vclocks(inherited, prev_vclock)
        if origin_cid:
            clock = tick_vclock(clock, origin_cid)
        self._data[key] = TombstoneEntry(
            sha256=sha256sum,
            version_id=new_version_id(),
            origin_cid=origin_cid,
            ts=ts,
            vclock=clock,
        )
        self._mark_dirty(key)

    # ── maintenance ─────────────────────────────────────────────────
    def prune(self, now: int | float | None = None) -> int:
        """Remove expired markers; return the number of entries dropped.

        Purely a storage bound: correctness never depends on pruning, because
        deletion decisions are causal. A peer offline beyond the retention
        window may still resurrect a file, which is why the mass-deletion
        guard remains the last line of defense (ADR-0015).
        """
        if self.ttl_seconds <= 0:
            return 0
        cutoff = (int(now) if now is not None else int(time.time())) - self.ttl_seconds
        expired = [k for k, v in self._data.items() if v["ts"] < cutoff]
        for k in expired:
            del self._data[k]
            self._mark_deleted(k)
        return len(expired)

    # ── transport (causal merge) ────────────────────────────────────
    def to_payload(self) -> dict[str, TombstoneEntry]:
        """Return a JSON-serializable copy keyed by hashed path."""
        return {
            k: TombstoneEntry(
                sha256=v["sha256"],
                version_id=v["version_id"],
                origin_cid=v["origin_cid"],
                ts=v["ts"],
                vclock=dict(v["vclock"]),
            )
            for k, v in self._data.items()
        }

    def merge(self, payload: dict[str, TombstoneEntry] | None) -> int:
        """Merge a remote payload causally; return change count.

        The payload is untrusted (it may come from any LAN peer via gossip):
        entries are strictly validated, invalid ones are skipped silently and
        the store size is capped. For each key the merge keeps the dominant
        clock; on true concurrency a deterministic content-based tie-break
        decides — never the deletion timestamp.
        """
        if not isinstance(payload, dict):
            # A truthy non-dict payload (JSON array/string) must not crash the
            # merge — it simply carries no entries.
            return 0
        changed = 0
        now = int(time.time())
        for key, entry in (payload or {}).items():
            clean = _sanitize_entry(key, entry, now)
            if clean is None:
                continue
            existing = self._data.get(key)
            if existing is None:
                if len(self._data) >= tombstone.TOMBSTONE_MAX_ENTRIES:
                    break
                self._data[key] = clean
                self._mark_dirty(key)
                changed += 1
                continue
            if tombstone_merge_decision(existing, clean) == "adopt":
                self._data[key] = clean
                self._mark_dirty(key)
                changed += 1
        return changed

    # ── persistence hooks (see CausalStoreBase.load/save) ──────────
    def _max_entries(self) -> int | None:
        return tombstone.TOMBSTONE_MAX_ENTRIES

    def _iter_rows(self, db: StateDb, folder_id: str) -> list[sqlite3.Row]:
        return db.iter_tombstones(folder_id)

    def _parse_row(self, row: sqlite3.Row, now: int) -> tuple[str, TombstoneEntry] | None:
        return _parse_tombstone_row(row, now)

    def _delete_rows(self, db: StateDb, folder_id: str, keys: list[str]) -> int:
        return db.delete_tombstones(folder_id, keys)

    def _upsert_row(self, db: StateDb, folder_id: str, key: str, entry: TombstoneEntry) -> None:
        db.upsert_tombstone(
            folder_id,
            key,
            sha256sum=entry["sha256"],
            version_id=entry["version_id"],
            origin_cid=entry["origin_cid"],
            ts=float(entry["ts"]),
            vclock=_vclock_to_json(entry["vclock"]),
        )
