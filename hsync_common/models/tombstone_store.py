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

import json
import sqlite3
import time
from pathlib import Path

from . import tombstone
from ._util import tombstone_key
from .sqlstore import StateDb, get_state_db
from .tombstone import (
    TOMBSTONE_TTL_DAYS_DEFAULT,
    TombstoneEntry,
    _sanitize_entry,
    tombstone_merge_decision,
)
from .version import merge_vclocks, new_version_id, tick_vclock

__all__ = ["TombstoneStore"]


def _vclock_to_json(vclock: dict[str, int]) -> str:
    """Serialize a validated vector clock for the ``tombstones.vclock`` column."""
    return json.dumps(vclock, separators=(",", ":"), sort_keys=True)


def _tombstone_from_row(row: object, now: int) -> tuple[str, TombstoneEntry] | None:
    """Sanitize a SQLite tombstone row the same way as an untrusted payload."""
    mapping = dict(row)  # type: ignore[arg-type]
    key = mapping.get("key")
    entry = {
        "sha256": mapping.get("sha256sum"),
        "version_id": mapping.get("version_id", ""),
        "origin_cid": mapping.get("origin_cid"),
        "ts": mapping.get("ts", 0),
        "vclock": mapping.get("vclock"),
    }
    raw_vclock = entry["vclock"]
    if isinstance(raw_vclock, str):
        try:
            entry["vclock"] = json.loads(raw_vclock)
        except ValueError:
            return None
    clean = _sanitize_entry(key, entry, now)
    if clean is None or not isinstance(key, str):
        return None
    return key, clean


class TombstoneStore:
    """In-memory tombstone map with SQLite persistence and causal merge."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        folder_id: str | None = None,
        *,
        ttl_days: int = TOMBSTONE_TTL_DAYS_DEFAULT,
        canonical_path: str = "",
    ):
        self.db_path = str(db_path) if db_path is not None else None
        self.folder_id = folder_id
        self.canonical_path = canonical_path
        self.ttl_seconds = max(0, int(ttl_days)) * 86400
        self._data: dict[str, TombstoneEntry] = {}
        self._db: StateDb | None = None
        self._dirty = False

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
        self._dirty = True

    def clear(self, relpath: str) -> bool:
        """Drop the marker for a relative path (the path was re-created).

        The deletion is superseded by the new content version, whose clock
        dominates the tombstone clock; the marker itself is removed so peers
        never apply a stale deletion to the re-created file.
        """
        dropped = self._data.pop(tombstone_key(relpath), None) is not None
        if dropped:
            self._dirty = True
        return dropped

    # ── query ───────────────────────────────────────────────────────
    def get(self, relpath: str) -> TombstoneEntry | None:
        """Return the marker for a relative path, if any."""
        return self._data.get(tombstone_key(relpath))

    def __len__(self) -> int:
        return len(self._data)

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
        if expired:
            self._dirty = True
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
                changed += 1
                continue
            if tombstone_merge_decision(existing, clean) == "adopt":
                self._data[key] = clean
                changed += 1
        if changed:
            self._dirty = True
        return changed

    # ── persistence ─────────────────────────────────────────────────
    def _backend(self) -> StateDb | None:
        """Return the shared DB handle when ``db_path`` + ``folder_id`` are set."""
        if not self.db_path or not self.folder_id:
            return None
        if self._db is None:
            self._db = get_state_db(self.db_path)
        return self._db

    def load(self) -> None:
        """Load markers from the installation DB, if configured."""
        db = self._backend()
        if db is None or self.folder_id is None:
            return
        db.ensure_folder(self.folder_id, self.canonical_path)
        now = int(time.time())
        data: dict[str, TombstoneEntry] = {}
        for row in db.iter_tombstones(self.folder_id):
            if len(data) >= tombstone.TOMBSTONE_MAX_ENTRIES:
                break
            parsed = _tombstone_from_row(row, now)
            if parsed is None:
                continue
            key, clean = parsed
            data[key] = clean
        self._data = data
        self._dirty = False

    def save(self) -> None:
        """Persist markers to the installation DB (one transaction)."""
        db = self._backend()
        if db is None or self.folder_id is None or not self._dirty:
            return
        db.ensure_folder(self.folder_id, self.canonical_path)
        own_txn = False
        try:
            db.begin_immediate()
            own_txn = True
        except sqlite3.OperationalError:
            own_txn = False
        try:
            db.retain_tombstones(self.folder_id, list(self._data.keys()))
            for key, entry in self._data.items():
                db.upsert_tombstone(
                    self.folder_id,
                    key,
                    sha256sum=entry["sha256"],
                    version_id=entry["version_id"],
                    origin_cid=entry["origin_cid"],
                    ts=float(entry["ts"]),
                    vclock=_vclock_to_json(entry["vclock"]),
                )
            if own_txn:
                db.commit()
            self._dirty = False
        except Exception:
            if own_txn:
                db.rollback()
            raise
