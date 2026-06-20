# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Per-file version metadata and clock-independent three-way merge for HSYNC.

HSYNC is *master-authoritative* (the server, or the elected LAN master, is the
source of truth), not a CRDT. To resolve concurrent edits correctly without
trusting wall-clock timestamps, each peer remembers, per path, the content hash
it last agreed on with the master (``base_hash``) plus the version lineage that
produced it (``change_id``, ``origin_cid``). Comparing the local hash, the
remote hash and this base lets a peer tell whether only the local side, only the
remote side, or *both* sides changed since the last successful sync — the same
three-way strategy used by Syncthing/git, immune to clock skew.

The store mirrors :class:`hsync_common.models.tombstone.TombstoneStore`: a
hidden ``.hsyncstate`` side-car with atomic JSON persistence. It is private to
each peer and never exchanged.
"""

import json
import secrets
import time
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

from .tombstone import relpath_in_bucket, tombstone_key

__all__ = [
    "FileVersion",
    "SyncDecision",
    "SyncStateStore",
    "new_change_id",
    "relpath_in_bucket",
    "resolve_three_way",
]

# Length (hex chars) of a freshly minted change id; 16 bytes = 128 bits entropy.
_CHANGE_ID_BYTES = 16


class FileVersion(TypedDict):
    """Recorded common-ancestor version for a single path."""

    base_hash: str  # content hash agreed on at the last successful sync
    change_id: str  # opaque id of that version (lineage, not content-derived)
    origin_cid: str | None  # peer that authored the version (None if remote/unknown)
    ts: int  # wall-clock timestamp the base was recorded (unix seconds)


class SyncDecision(StrEnum):
    """Outcome of a three-way comparison between local, remote and base."""

    in_sync = "in_sync"  # local == remote, nothing to do
    upload = "upload"  # only the local side changed since base
    download = "download"  # only the remote side changed since base
    conflict = "conflict"  # both sides changed since base (divergence)
    unknown_base = "unknown_base"  # no recorded base: caller falls back to legacy


def new_change_id() -> str:
    """Mint a fresh, opaque version id for a locally authored change."""
    return secrets.token_hex(_CHANGE_ID_BYTES)


def resolve_three_way(
    local_hash: str | None,
    remote_hash: str | None,
    base_hash: str | None,
) -> SyncDecision:
    """Decide the sync direction from content hashes alone (clock-independent).

    Args:
        local_hash: SHA-256 of the local file (None if absent).
        remote_hash: SHA-256 of the remote file (None if absent).
        base_hash: SHA-256 of the last-synced common ancestor (None if unknown).

    Returns:
        The :class:`SyncDecision`. ``unknown_base`` signals the caller to fall
        back to its legacy mtime/hash heuristic (e.g. on a first-ever sync).
    """
    if local_hash == remote_hash:
        return SyncDecision.in_sync
    if base_hash is None:
        return SyncDecision.unknown_base
    if local_hash == base_hash:
        # Local untouched since base, remote moved on -> take remote.
        return SyncDecision.download
    if remote_hash == base_hash:
        # Remote untouched since base, local moved on -> push local.
        return SyncDecision.upload
    # Neither side matches the common ancestor: genuine divergence.
    return SyncDecision.conflict


class SyncStateStore:
    """In-memory path->version map with atomic JSON persistence."""

    def __init__(self, path: str | None = None):
        self.path = path
        self._data: dict[str, FileVersion] = {}

    # ── mutation ────────────────────────────────────────────────────
    def record(
        self,
        relpath: str,
        base_hash: str,
        change_id: str | None = None,
        origin_cid: str | None = None,
        timestamp: int | float | None = None,
    ) -> None:
        """Record (overwrite) the agreed base version for a relative path."""
        ts = int(timestamp) if timestamp is not None else int(time.time())
        self._data[tombstone_key(relpath)] = FileVersion(
            base_hash=base_hash,
            change_id=change_id or new_change_id(),
            origin_cid=origin_cid,
            ts=ts,
        )

    def clear(self, relpath: str) -> bool:
        """Drop the recorded version for a path (e.g. on deletion)."""
        return self._data.pop(tombstone_key(relpath), None) is not None

    def retain(self, relpaths: list[str]) -> int:
        """Drop entries for paths not in ``relpaths``; return the drop count.

        Keeps the store bounded: a version is only useful while its file still
        participates in the sync, so stale entries are garbage-collected.
        """
        keep = {tombstone_key(rp) for rp in relpaths}
        stale = [k for k in self._data if k not in keep]
        for k in stale:
            del self._data[k]
        return len(stale)

    # ── query ───────────────────────────────────────────────────────
    def get(self, relpath: str) -> FileVersion | None:
        """Return the recorded version for a relative path, if any."""
        return self._data.get(tombstone_key(relpath))

    def base_hash(self, relpath: str) -> str | None:
        """Return just the recorded base content hash for a path, if any."""
        entry = self.get(relpath)
        return entry["base_hash"] if entry else None

    def __len__(self) -> int:
        return len(self._data)

    # ── persistence ─────────────────────────────────────────────────
    def load(self) -> None:
        """Load recorded versions from the backing JSON file, if present."""
        if not self.path:
            return
        p = Path(self.path)
        if not p.exists():
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = raw.get("versions", {}) if isinstance(raw, dict) else {}
        data: dict[str, FileVersion] = {}
        for key, entry in entries.items():
            if isinstance(entry, dict) and "base_hash" in entry:
                data[key] = FileVersion(
                    base_hash=str(entry["base_hash"]),
                    change_id=str(entry.get("change_id", "")),
                    origin_cid=entry.get("origin_cid"),
                    ts=int(entry.get("ts", 0)),
                )
        self._data = data

    def save(self) -> None:
        """Persist recorded versions atomically to the backing JSON file."""
        if not self.path:
            return
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps({"versions": self._data}), encoding="utf-8")
        tmp.replace(p)
