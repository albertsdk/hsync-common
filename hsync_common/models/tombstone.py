# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Tombstone (deletion marker) store for HSYNC.

A tombstone records that a file was deleted, so that a peer which was offline
at deletion time does not resurrect the file during a full reconciliation.
Each entry maps a hashed bucket-relative path to the deletion timestamp and
the content hash of the removed file.

The store is reused on both sides:
- the server (and a LAN master) persists tombstones and serves them to clients;
- a client/slave merges them using a last-writer-wins (LWW) strategy on the
  deletion timestamp.
"""

import json
import time
from hashlib import sha256
from pathlib import Path
from typing import TypedDict

# Default retention window before a tombstone is garbage-collected. Keeping a
# bounded window caps file growth and lets a path be reused after a long time.
TOMBSTONE_TTL_DAYS_DEFAULT = 30


class TombstoneEntry(TypedDict):
    """Serialized deletion marker for a single path."""

    ts: int  # deletion wall-clock timestamp (unix seconds)
    sha256: str | None  # content hash of the deleted file (None if unknown)


def tombstone_key(relpath: str) -> str:
    """Return the stable, privacy-preserving key for a bucket-relative path."""
    return sha256(relpath.encode("utf-8")).hexdigest()


class TombstoneStore:
    """In-memory tombstone map with JSON persistence and LWW merge."""

    def __init__(self, path: str | None = None, ttl_days: int = TOMBSTONE_TTL_DAYS_DEFAULT):
        self.path = path
        self.ttl_seconds = max(0, int(ttl_days)) * 86400
        self._data: dict[str, TombstoneEntry] = {}

    # ── mutation ────────────────────────────────────────────────────
    def record(
        self,
        relpath: str,
        sha256sum: str | None = None,
        timestamp: int | float | None = None,
    ) -> None:
        """Record (or refresh, LWW) a deletion marker for a relative path."""
        ts = int(timestamp) if timestamp is not None else int(time.time())
        key = tombstone_key(relpath)
        existing = self._data.get(key)
        if existing is None or ts >= existing["ts"]:
            self._data[key] = TombstoneEntry(ts=ts, sha256=sha256sum)

    def clear(self, relpath: str) -> bool:
        """Drop the marker for a relative path (e.g. when it is re-created)."""
        return self._data.pop(tombstone_key(relpath), None) is not None

    # ── query ───────────────────────────────────────────────────────
    def get(self, relpath: str) -> TombstoneEntry | None:
        """Return the marker for a relative path, if any."""
        return self._data.get(tombstone_key(relpath))

    def get_by_key(self, key: str) -> TombstoneEntry | None:
        """Return the marker for an already-hashed key, if any."""
        return self._data.get(key)

    def __len__(self) -> int:
        return len(self._data)

    # ── maintenance ─────────────────────────────────────────────────
    def prune(self, now: int | float | None = None) -> int:
        """Remove expired markers; return the number of entries dropped."""
        if self.ttl_seconds <= 0:
            return 0
        cutoff = (int(now) if now is not None else int(time.time())) - self.ttl_seconds
        expired = [k for k, v in self._data.items() if v["ts"] < cutoff]
        for k in expired:
            del self._data[k]
        return len(expired)

    # ── transport (LWW) ─────────────────────────────────────────────
    def to_payload(self) -> dict[str, TombstoneEntry]:
        """Return a JSON-serializable copy keyed by hashed path."""
        return {k: TombstoneEntry(ts=v["ts"], sha256=v["sha256"]) for k, v in self._data.items()}

    def merge(self, payload: dict[str, TombstoneEntry] | None) -> int:
        """Merge a remote payload using last-writer-wins; return change count."""
        changed = 0
        for key, entry in (payload or {}).items():
            if not isinstance(entry, dict) or "ts" not in entry:
                continue
            ts = int(entry["ts"])
            existing = self._data.get(key)
            if existing is None or ts > existing["ts"]:
                self._data[key] = TombstoneEntry(ts=ts, sha256=entry.get("sha256"))
                changed += 1
        return changed

    # ── persistence ─────────────────────────────────────────────────
    def load(self) -> None:
        """Load markers from the backing JSON file, if configured/present."""
        if not self.path:
            return
        p = Path(self.path)
        if not p.exists():
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        entries = raw.get("tombstones", {}) if isinstance(raw, dict) else {}
        data: dict[str, TombstoneEntry] = {}
        for key, entry in entries.items():
            if isinstance(entry, dict) and "ts" in entry:
                data[key] = TombstoneEntry(ts=int(entry["ts"]), sha256=entry.get("sha256"))
        self._data = data

    def save(self) -> None:
        """Persist markers atomically to the backing JSON file, if configured."""
        if not self.path:
            return
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps({"tombstones": self._data}), encoding="utf-8")
        tmp.replace(p)
