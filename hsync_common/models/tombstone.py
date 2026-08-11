# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Causal tombstone (deletion marker) store for HSYNC.

A tombstone records that a file was deleted, so that a peer which was offline
at deletion time does not resurrect the file during a full reconciliation.
Each entry maps a hashed bucket-relative path to the **causal** metadata of
the deletion: the content hash of the removed file, an opaque version id, the
author cid, the informational wall-clock timestamp, and a **vector clock**
summarising the causal history of the path at deletion time (ADR-0003).

Deletions follow the same causal model as content edits: the clock decides,
never the wall clock. The recorded clock is the stored version clock advanced
(ticked) by the deleter, so delete-vs-recreate and delete-vs-delete are
resolved by causal dominance — ``ts`` is informational only and is consulted
exclusively by the TTL prune (storage GC) and by anti-poisoning validation.

The store is reused on both sides:
- the server (and a LAN master) persists tombstones and serves them to clients;
- a client/slave merges them causally (dominance, then deterministic tie-break).

Persistence is the installation SQLite database (``syncstate.db``, ADR-0025),
keyed by folder UUID. The wire shape (``to_payload()``) is unchanged.

Path helpers (``tombstone_key`` / ``relpath_in_bucket``) and the wire-timestamp
parser are re-exported from ``._util`` for the historic consumers.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import TypedDict

from hsync_common.hashing import is_sha256_hex

from ._util import _parse_wire_timestamp, relpath_in_bucket, tombstone_key
from .event import is_valid_cid
from .sqlstore import StateDb, get_state_db
from .version import (
    VCLOCK_MAX_ENTRIES,
    VClockOrder,
    compare_vclocks,
    merge_vclocks,
    new_version_id,
    tick_vclock,
)

__all__ = [
    "TOMBSTONE_MAX_CLOCK_SKEW_SECONDS",
    "TOMBSTONE_MAX_ENTRIES",
    "TOMBSTONE_TTL_DAYS_DEFAULT",
    "TombstoneEntry",
    "TombstoneStore",
    "relpath_in_bucket",
    "tombstone_key",
    "tombstone_merge_decision",
]

# Default retention window before a tombstone is garbage-collected. This is
# purely a *storage* bound: correctness never depends on it, because deletion
# decisions are causal. A 90-day window gives offline peers a comfortable
# margin to reconnect and learn about a deletion (ADR-0003).
TOMBSTONE_TTL_DAYS_DEFAULT = 90

# Tolerance for clock skew between peers when validating tombstone timestamps.
# A deletion timestamp further in the future than this is rejected: an
# attacker could otherwise plant far-future markers that never expire.
TOMBSTONE_MAX_CLOCK_SKEW_SECONDS = 300

# Hard cap on the number of tombstones held in the store. Bounds memory/disk
# growth against a hostile peer flooding the gossip channel with markers.
TOMBSTONE_MAX_ENTRIES = 100_000


class TombstoneEntry(TypedDict):
    """Serialized causal deletion marker for a single path.

    Consumers: ``hsync-common`` (store), ``hsync-server`` / ``hsync-client``
    (``tombstones.py`` wrappers and gossip endpoints), ``hsync-android``
    (``Tombstones.kt`` mirror) and the shared fixtures.
    """

    sha256: str | None  # content hash of the deleted file (None if unknown)
    version_id: str  # opaque id of the deletion (lineage, not content-derived)
    origin_cid: str | None  # peer that authored the deletion (None if unknown)
    ts: int  # wall-clock timestamp of the deletion (informational only)
    vclock: dict[str, int]  # causal history at deletion time: node cid -> counter


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


def _parse_vclock(raw: object) -> dict[str, int] | None:
    """Strictly parse a ``vclock`` from an untrusted payload.

    Returns ``None`` on any structural violation (missing/non-dict clock,
    more than ``VCLOCK_MAX_ENTRIES`` entries, ``bool`` or negative counters,
    non-cid keys). An explicitly empty ``{}`` is a valid clock: it carries no
    causal information and is dominated by any non-empty one.
    """
    if not isinstance(raw, dict) or len(raw) > VCLOCK_MAX_ENTRIES:
        return None
    clock: dict[str, int] = {}
    for key, value in raw.items():
        # bool is a subclass of int — reject it explicitly (a `True` counter
        # would silently parse as 1, masking a corrupt payload).
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        if not is_valid_cid(key):
            return None
        clock[key] = value
    return clock


def _sanitize_entry(
    key: object,
    entry: object,
    now: int,
) -> TombstoneEntry | None:
    """Validate a (key, entry) pair from an untrusted payload.

    Rejects malformed keys, missing/non-numeric timestamps, timestamps in the
    future (beyond clock-skew tolerance), malformed content hashes and any
    structurally invalid vector clock. A tombstone without a valid ``vclock``
    is **not** a legal deletion marker and is dropped.

    Args:
        key: The tombstone key (expected sha256 hex of the relpath).
        entry: The candidate tombstone entry.
        now: Current unix timestamp used for the future-timestamp check.

    Returns:
        A sanitized :class:`TombstoneEntry`, or ``None`` when invalid.
    """
    if not _is_valid_key(key) or not isinstance(entry, dict) or "ts" not in entry:
        return None
    ts = _parse_wire_timestamp(entry["ts"])  # type: ignore[index]
    if ts is None or ts <= 0 or ts > now + TOMBSTONE_MAX_CLOCK_SKEW_SECONDS:
        return None
    sha = entry.get("sha256")  # type: ignore[union-attr]
    if not _is_valid_sha256(sha):
        return None
    vclock = _parse_vclock(entry.get("vclock"))  # type: ignore[union-attr]
    if vclock is None:
        return None
    version_id = entry.get("version_id")  # type: ignore[union-attr]
    if not isinstance(version_id, str):
        version_id = ""
    origin_cid = entry.get("origin_cid")  # type: ignore[union-attr]
    if origin_cid is not None and not (isinstance(origin_cid, str) and is_valid_cid(origin_cid)):
        return None
    return TombstoneEntry(  # type: ignore[typeddict-item]
        sha256=sha,
        version_id=version_id,
        origin_cid=origin_cid,
        ts=ts,
        vclock=vclock,
    )


def _prefer_incoming(existing: TombstoneEntry, incoming: TombstoneEntry) -> bool:
    """Deterministic tie-break for concurrent tombstones (never wall clock).

    Prefers the incoming entry when its content lineage sorts higher:
    content hash first, then version id, then author cid. Both computed
    locally from the same inputs, so all nodes pick the same winner.
    """
    if (incoming["sha256"] or "") != (existing["sha256"] or ""):
        return (incoming["sha256"] or "") > (existing["sha256"] or "")
    if incoming["version_id"] != existing["version_id"]:
        return incoming["version_id"] > existing["version_id"]
    return (incoming["origin_cid"] or "") > (existing["origin_cid"] or "")


def tombstone_merge_decision(existing: TombstoneEntry | None, incoming: TombstoneEntry) -> str:
    """Pure causal decision for merging one remote tombstone ("adopt" | "keep").

    The merge is decided by causal dominance of the vector clocks; on true
    concurrency a deterministic content-based tie-break applies. Extracted as
    a pure function so the shared golden fixtures can compute expected
    outcomes from the algorithm itself and the Android mirror can run an
    exact parity test (ADR-0003).

    Consumers: ``hsync-common`` (``TombstoneStore.merge``, fixtures builder),
    ``hsync-android`` (``Tombstones.kt`` parity test).
    """
    if existing is None:
        return "adopt"
    order = compare_vclocks(existing["vclock"], incoming["vclock"])
    if order is VClockOrder.dominated:
        return "adopt"
    if order is VClockOrder.dominates:
        return "keep"
    return "adopt" if _prefer_incoming(existing, incoming) else "keep"


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
                if len(self._data) >= TOMBSTONE_MAX_ENTRIES:
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
            if len(data) >= TOMBSTONE_MAX_ENTRIES:
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
