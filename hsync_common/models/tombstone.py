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

from hsync_common.hashing import is_sha256_hex

# Default retention window before a tombstone is garbage-collected. Keeping a
# bounded window caps file growth and lets a path be reused after a long time.
TOMBSTONE_TTL_DAYS_DEFAULT = 30

# Tolerance for clock skew between peers when validating tombstone timestamps.
# A deletion timestamp further in the future than this is rejected: an
# attacker could otherwise plant far-future markers that never expire and
# force-delete any local file whose content hash they know.
TOMBSTONE_MAX_CLOCK_SKEW_SECONDS = 300

# Hard cap on the number of tombstones held in the store. Bounds memory/disk
# growth against a hostile peer flooding the gossip channel with markers.
TOMBSTONE_MAX_ENTRIES = 100_000


class TombstoneEntry(TypedDict):
    """Serialized deletion marker for a single path."""

    ts: int  # deletion wall-clock timestamp (unix seconds)
    sha256: str | None  # content hash of the deleted file (None if unknown)


def _is_valid_key(key: object) -> bool:
    """Return True when *key* looks like a sha256 hex digest (tombstone key).

    Tombstone keys are always `hashlib.sha256(...).hexdigest()` output, i.e.
    lowercase: uppercase variants from a peer are rejected (they would never
    match a locally computed key anyway).
    """
    return is_sha256_hex(key) and key == key.lower()


def _is_valid_sha256(value: object) -> bool:
    """Return True when *value* is None or a sha256 hex digest."""
    return value is None or _is_valid_key(value)


def _sanitize_entry(
    key: object,
    entry: object,
    now: int,
) -> TombstoneEntry | None:
    """Validate a (key, entry) pair from an untrusted payload.

    Rejects malformed keys, missing/non-numeric timestamps, timestamps in
    the future (beyond clock-skew tolerance) and malformed content hashes.

    Args:
        key: The tombstone key (expected sha256 hex of the relpath).
        entry: The candidate tombstone entry.
        now: Current unix timestamp used for the future-timestamp check.

    Returns:
        A sanitized :class:`TombstoneEntry`, or ``None`` when invalid.
    """
    if not _is_valid_key(key) or not isinstance(entry, dict) or "ts" not in entry:
        return None
    raw_ts = entry["ts"]  # type: ignore[index]
    if isinstance(raw_ts, bool):
        # bool is an int subclass: reject it on the RAW value, before int()
        # would silently turn True into a valid-looking timestamp of 1.
        return None
    try:
        ts = int(raw_ts)  # type: ignore[call-overload]
    except (TypeError, ValueError, OverflowError):
        # Non-numeric ts, or a non-finite float (JSON ``Infinity``/``NaN``
        # are accepted by json.loads and would crash int() with
        # OverflowError/ValueError) — reject instead of blowing up the merge.
        return None
    if ts <= 0 or ts > now + TOMBSTONE_MAX_CLOCK_SKEW_SECONDS:
        return None
    sha = entry.get("sha256")  # type: ignore[union-attr]
    if not _is_valid_sha256(sha):
        return None
    return TombstoneEntry(ts=ts, sha256=sha)  # type: ignore[typeddict-item]


def tombstone_key(relpath: str) -> str:
    """Return the stable, privacy-preserving key for a bucket-relative path."""
    return sha256(relpath.encode("utf-8")).hexdigest()


def relpath_in_bucket(abs_path: str, bucket_dir: str) -> str:
    """Return the bucket-relative path used as the tombstone identity.

    Uses :meth:`pathlib.Path.relative_to` so a sibling-prefix directory
    (e.g. ``/data/bucket2`` vs ``/data/bucket``) is never confused with
    the bucket itself: ``removeprefix`` would strip the shared prefix and
    produce a bogus relative path (``2/x``), while ``relative_to`` raises
    ``ValueError`` for paths outside the bucket.
    """
    try:
        rel = str(Path(str(abs_path)).relative_to(str(bucket_dir)))
        # relative_to of the bucket itself yields ".", normalise to "" so the
        # caller treats the bucket root as an empty relative path.
        return "" if rel == "." else rel
    except ValueError:
        return ""


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
        """Merge a remote payload using last-writer-wins; return change count.

        The payload is untrusted (it may come from any LAN peer via gossip):
        entries are validated and the store size is capped. Invalid entries
        are skipped silently so one bad marker cannot poison the merge.
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
            if existing is None and len(self._data) >= TOMBSTONE_MAX_ENTRIES:
                break
            if existing is None or clean["ts"] > existing["ts"]:
                self._data[key] = clean
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
        if not isinstance(entries, dict):
            # A malformed side-car (e.g. "tombstones" is a list) must not
            # crash startup — treat it as empty.
            return
        now = int(time.time())
        data: dict[str, TombstoneEntry] = {}
        for key, entry in entries.items():
            if len(data) >= TOMBSTONE_MAX_ENTRIES:
                break
            clean = _sanitize_entry(key, entry, now)
            if clean is not None:
                data[key] = clean
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
