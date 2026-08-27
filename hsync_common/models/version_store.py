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

import sqlite3
import time

from ._store_base import CausalStoreBase
from ._util import _parse_stored_vclock, _parse_wire_timestamp, _vclock_to_json, tombstone_key
from .sqlstore import StateDb
from .version import FileVersion, new_version_id, parse_vclock

__all__ = ["SyncStateStore"]


def _parse_version_row(row: sqlite3.Row, _now: int) -> tuple[str, FileVersion] | None:
    """Build a ``(key, FileVersion)`` pair from a SQLite row, or ``None`` if unusable.

    ``_now`` is unused (versions carry no future-timestamp check) but is part of
    the shared row-parser contract so both stores expose the same hook shape.
    """
    mapping = dict(row)
    key = mapping.get("key")
    base_hash = mapping.get("base_hash")
    if not isinstance(key, str) or not isinstance(base_hash, str) or not base_hash:
        return None
    ts = _parse_wire_timestamp(mapping.get("ts", 0))
    if ts is None:
        return None
    vclock = parse_vclock(_parse_stored_vclock(mapping.get("vclock")))
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
    return key, FileVersion(
        base_hash=base_hash,
        version_id=str(version_id) if version_id is not None else "",
        origin_cid=origin if isinstance(origin, str) else None,
        ts=ts,
        vclock=vclock,
        corrected_mtime=corrected,
    )


class SyncStateStore(CausalStoreBase[FileVersion]):
    """In-memory path→version map persisted in the installation SQLite DB."""

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

    # ── persistence hooks (see CausalStoreBase.load/save) ──────────
    def _iter_rows(self, db: StateDb, folder_id: str) -> list[sqlite3.Row]:
        return db.iter_versions(folder_id)

    def _parse_row(self, row: sqlite3.Row, now: int) -> tuple[str, FileVersion] | None:
        return _parse_version_row(row, now)

    def _retain_rows(self, db: StateDb, folder_id: str, keep: list[str]) -> int:
        return db.retain_versions(folder_id, keep)

    def _upsert_row(self, db: StateDb, folder_id: str, key: str, entry: FileVersion) -> None:
        db.upsert_version(
            folder_id,
            key,
            base_hash=entry["base_hash"],
            version_id=entry["version_id"],
            origin_cid=entry["origin_cid"],
            ts=float(entry["ts"]),
            vclock=_vclock_to_json(entry["vclock"]),
            corrected_mtime=float(entry["corrected_mtime"]),
        )
