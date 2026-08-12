# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
SQLite-backed persistence for per-file version metadata (:class:`SyncStateStore`).

The causal model itself (vector clocks, :func:`~.version.resolve_three_way`)
lives in :mod:`.version`; this module owns only the storage layer: an in-memory
path→version map persisted in the installation SQLite database
(``syncstate.db``, ADR-0025), keyed by a folder UUID. It is private to each
peer and never exchanged; the wire form is :class:`~.version.VersionInfo`.

The stored clock is validated as untrusted on load (structurally malformed
entries are dropped) so a corrupted row degrades entry-by-entry rather than
crashing startup or poisoning the merge base.

Consumers: ``hsync-client`` (``sync_state`` store wrapper), ``hsync-server``
(``versions.py`` per-bucket stores), ``hsync-android`` (``Version.kt``
``SyncStateStore`` mirror). Re-exported from :mod:`.version` for the historic
import path.
"""

import json
import sqlite3
import time
from pathlib import Path

from . import version
from ._util import _parse_wire_timestamp, tombstone_key
from .event import is_valid_cid
from .sqlstore import StateDb, get_state_db
from .version import FileVersion, new_version_id

__all__ = ["SyncStateStore"]


def _parse_stored_vclock(raw: object) -> dict[str, int] | None:
    """Parse a ``vclock`` read from local storage (validated as untrusted).

    A structurally invalid clock (non-dict, oversized, ``bool``/negative
    counters, non-cid keys, unknown-types) makes the whole entry unusable:
    the caller drops it rather than fabricating an empty clock, which could
    mask a corrupted common ancestor and flip a sync decision.
    """
    if not isinstance(raw, dict) or len(raw) > version.VCLOCK_MAX_ENTRIES:
        return None
    vclock: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        key_str = str(key) if isinstance(key, str) else None
        if key_str is None or not is_valid_cid(key_str):
            return None
        vclock[key_str] = value
    return vclock


def _vclock_to_json(vclock: dict[str, int]) -> str:
    """Serialize a validated vector clock for the ``versions.vclock`` column."""
    return json.dumps(vclock, separators=(",", ":"), sort_keys=True)


def _file_version_from_row(row: object) -> FileVersion | None:
    """Build a :class:`FileVersion` from a SQLite row, or ``None`` if unusable."""
    mapping = dict(row)  # type: ignore[arg-type]
    base_hash = mapping.get("base_hash")
    if not isinstance(base_hash, str) or not base_hash:
        return None
    ts = _parse_wire_timestamp(mapping.get("ts", 0))
    if ts is None:
        return None
    raw_vclock = mapping.get("vclock")
    parsed_clock: object
    if isinstance(raw_vclock, str):
        try:
            parsed_clock = json.loads(raw_vclock)
        except ValueError:
            return None
    else:
        parsed_clock = raw_vclock
    vclock = _parse_stored_vclock(parsed_clock)
    if vclock is None:
        return None
    raw_corrected = mapping.get("corrected_mtime")
    if raw_corrected is None:
        corrected = 0
    else:
        corrected = _parse_wire_timestamp(raw_corrected)
        if corrected is None:
            return None
    origin = mapping.get("origin_cid")
    version_id = mapping.get("version_id", "")
    return FileVersion(
        base_hash=base_hash,
        version_id=str(version_id) if version_id is not None else "",
        origin_cid=origin if isinstance(origin, str) else None,
        ts=ts,
        vclock=vclock,
        corrected_mtime=corrected,
    )


class SyncStateStore:
    """In-memory path→version map persisted in the installation SQLite DB."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        folder_id: str | None = None,
        *,
        canonical_path: str = "",
    ):
        self.db_path = str(db_path) if db_path is not None else None
        self.folder_id = folder_id
        self.canonical_path = canonical_path
        self._data: dict[str, FileVersion] = {}
        self._db: StateDb | None = None
        self._dirty = False

    # ── mutation ────────────────────────────────────────────────────
    def record(
        self,
        relpath: str,
        base_hash: str,
        version_id: str | None = None,
        origin_cid: str | None = None,
        timestamp: int | float | None = None,
        vclock: dict[str, int] | None = None,
        corrected_mtime: int = 0,
    ) -> None:
        """Record (overwrite) the agreed base version for a relative path."""
        ts = int(timestamp) if timestamp is not None else int(time.time())
        self._data[tombstone_key(relpath)] = FileVersion(
            base_hash=base_hash,
            version_id=version_id or new_version_id(),
            origin_cid=origin_cid,
            ts=ts,
            vclock=dict(vclock) if vclock else {},
            corrected_mtime=corrected_mtime,
        )
        self._dirty = True

    def clear(self, relpath: str) -> bool:
        """Drop the recorded version for a path (e.g. on deletion)."""
        dropped = self._data.pop(tombstone_key(relpath), None) is not None
        if dropped:
            self._dirty = True
        return dropped

    def retain(self, relpaths: list[str]) -> int:
        """Drop entries for paths not in ``relpaths``; return the drop count.

        Keeps the store bounded: a version is only useful while its file still
        participates in the sync, so stale entries are garbage-collected.
        """
        keep = {tombstone_key(rp) for rp in relpaths}
        stale = [k for k in self._data if k not in keep]
        for k in stale:
            del self._data[k]
        if stale:
            self._dirty = True
        return len(stale)

    # ── query ───────────────────────────────────────────────────────
    def get(self, relpath: str) -> FileVersion | None:
        """Return the recorded version for a relative path, if any."""
        return self._data.get(tombstone_key(relpath))

    def base_hash(self, relpath: str) -> str | None:
        """Return just the recorded base content hash for a path, if any."""
        entry = self.get(relpath)
        return entry["base_hash"] if entry else None

    def iter_entries(self) -> list[tuple[str, FileVersion]]:
        """Return all (relpath, version) entries as a snapshot.

        Used by the sync engine to inspect the merge base so it can detect
        files that were deleted locally between one-shot sync cycles (the
        entry exists in the store but the file is no longer listed by
        get_files_local).
        """
        return list(self._data.items())

    def __len__(self) -> int:
        return len(self._data)

    # ── persistence ─────────────────────────────────────────────────
    def _backend(self) -> StateDb | None:
        """Return the shared DB handle when ``db_path`` + ``folder_id`` are set."""
        if not self.db_path or not self.folder_id:
            return None
        if self._db is None:
            self._db = get_state_db(self.db_path)
        return self._db

    def load(self) -> None:
        """Load recorded versions from the installation DB, if configured.

        Rows with a structurally invalid clock or missing mandatory fields
        are dropped entry-by-entry: a corrupted store degrades safely
        without crashing startup. Every accepted entry carries a valid clock,
        because sync decisions are causal (ADR-0022/ADR-0003).
        """
        db = self._backend()
        if db is None or self.folder_id is None:
            return
        db.ensure_folder(self.folder_id, self.canonical_path)
        data: dict[str, FileVersion] = {}
        for row in db.iter_versions(self.folder_id):
            parsed = _file_version_from_row(row)
            if parsed is None:
                continue
            data[str(row["key"])] = parsed
        self._data = data
        self._dirty = False

    def save(self) -> None:
        """Persist recorded versions to the installation DB (one transaction).

        No-op when the store is not dirty or has no backend. Callers that
        already hold a ``BEGIN IMMEDIATE`` (client ``flush``) still get a
        consistent snapshot: this method opens its own transaction only
        when none is active.
        """
        db = self._backend()
        if db is None or self.folder_id is None or not self._dirty:
            return
        db.ensure_folder(self.folder_id, self.canonical_path)
        own_txn = False
        try:
            db.begin_immediate()
            own_txn = True
        except sqlite3.OperationalError:
            # Nested flush inside an already-open transaction (LAN realtime
            # delete after a cycle BEGIN): write without starting another.
            own_txn = False
        try:
            db.retain_versions(self.folder_id, list(self._data.keys()))
            for key, entry in self._data.items():
                db.upsert_version(
                    self.folder_id,
                    key,
                    base_hash=entry["base_hash"],
                    version_id=entry["version_id"],
                    origin_cid=entry["origin_cid"],
                    ts=float(entry["ts"]),
                    vclock=_vclock_to_json(entry["vclock"]),
                    corrected_mtime=float(entry["corrected_mtime"]),
                )
            if own_txn:
                db.commit()
            self._dirty = False
        except Exception:
            if own_txn:
                db.rollback()
            raise
