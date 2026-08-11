# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Per-file version metadata and causal vector-clock merge for HSYNC.

HSYNC resolves concurrent edits with a **decentralized causal model**: every
node records, per path, the content hash it last agreed on with the cluster
(``base_hash``) plus a **vector clock** (``vclock``) summarising the causal
history of that version. Comparing the local clock, the remote clock and the
common ancestor lets a peer tell whether only one side moved on (dominance) or
both did (true concurrency), without trusting wall-clock timestamps — immune to
clock skew and to the false conflicts that arise when files relay through
intermediate nodes.

On a true divergence (concurrent clocks) a **chronological tie-break** picks the
winner: the version with the higher clock-offset-corrected ``corrected_mtime``
keeps the original path; when either side lacks the field (or the values tie)
the deterministic SHA-256 fallback decides, and the losing content is preserved
as a ``_conflicted_copy_`` (extrema ratio). No node is authoritative: the server
and the elected LAN master are transport hubs only; every node applies the same
algorithm (see ADR-0022 and ADR-0023).

Deletions follow the same clock: a tombstone inherits the stored version clock
for the path and is ticked by the deleter, so delete-vs-recreate and
delete-vs-delete are causal too (ADR-0003). The raw wall clock is never
consulted for any *causal* decision; it enters only the chronological tie-break
through the offset-corrected ``corrected_mtime`` (ADR-0023).

The store is an in-memory path→version map persisted in the installation
SQLite database (``syncstate.db``, ADR-0025), keyed by a folder UUID. It is
private to each peer and never exchanged; the wire form is :class:`VersionInfo`.

The stored clock itself carries the node's own causal history only. It is
validated as untrusted on load (structurally malformed entries are dropped)
so a corrupted row degrades entry-by-entry rather than crashing startup or
poisoning the merge base.
"""

import json
import secrets
import sqlite3
import time
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

from ._util import _parse_wire_timestamp, relpath_in_bucket, tombstone_key
from .event import is_valid_cid
from .sqlstore import StateDb, get_state_db

__all__ = [
    "FileVersion",
    "VCLOCK_MAX_ENTRIES",
    "VClockOrder",
    "VersionInfo",
    "SyncDecision",
    "SyncStateStore",
    "compare_vclocks",
    "merge_vclocks",
    "new_version_id",
    "parse_version_info",
    "relpath_in_bucket",
    "resolve_three_way",
    "tick_vclock",
]

# Length (hex chars) of a freshly minted version id; 16 bytes = 128 bits entropy.
_VERSION_ID_BYTES = 16

# Upper bound on the number of distinct node entries accepted in an ingested
# vector clock. A cluster is small by the LAN threat model, so this guards only
# against a maliciously bloated payload, not realistic growth.
VCLOCK_MAX_ENTRIES = 256


class FileVersion(TypedDict):
    """Recorded common-ancestor version for a single path (private, never exchanged).

    Consumers: ``hsync-client`` (``sync_state`` store wrapper), ``hsync-server``
    (``versions.py`` per-bucket stores), ``hsync-android`` (``Version.kt``
    ``SyncStateStore`` mirror).
    """

    base_hash: str  # content hash agreed on at the last successful sync
    version_id: str  # opaque id of that version (lineage, not content-derived)
    origin_cid: str | None  # peer that authored the version (None if unknown)
    ts: int  # wall-clock timestamp the base was recorded (information only)
    vclock: dict[str, int]  # causal history: node cid -> logical counter
    corrected_mtime: int  # local mtime + measured clock offset (ADR-0023)


class VersionInfo(TypedDict):
    """Wire form of a file's version metadata, carried inside ``FileDict["version"]``.

    Unlike :class:`FileVersion` it carries no ``base_hash``: the content hash of
    the version is the ``sha256sum`` of the enclosing ``FileDict``. Consumers:
    ``hsync-common`` (``FileDict``/event builders), ``hsync-server`` (listing
    JOIN, upload arbitration), ``hsync-client`` (remote listing/event decode),
    ``hsync-android`` (``FileInfo.version`` mirror) and the shared fixtures.
    """

    vclock: dict[str, int]
    version_id: str
    origin_cid: str | None
    ts: int
    corrected_mtime: int  # chronological tie-break value (0 ⇒ absent, hash fallback)


class VClockOrder(StrEnum):
    """Result of comparing two vector clocks.

    Consumers: ``hsync-common`` (``resolve_three_way``, tombstone merge),
    ``hsync-client`` (``sync._compare_files``) and ``hsync-android``
    (``Version.kt`` mirror).
    """

    equal = "equal"
    dominates = "dominates"  # the first argument strictly dominates the second
    dominated = "dominated"  # the first is strictly dominated by the second
    concurrent = "concurrent"  # neither dominates: true causal divergence


class SyncDecision(StrEnum):
    """Outcome of a causal three-way comparison.

    Consumers: ``hsync-client`` (``sync._compare_files``), ``hsync-android``
    (``Version.resolveThreeWay``) and the shared causal-resolution fixtures.
    """

    in_sync = "in_sync"  # local == remote, nothing to do
    upload = "upload"  # local causally ahead (or remote at base): push local
    download = "download"  # remote causally ahead (or local at base): take remote
    conflict_upload = (
        "conflict_upload"  # concurrent: local wins tie-break, upload (remote preserves loser)
    )
    conflict_download = (
        "conflict_download"  # concurrent: remote wins tie-break, preserve local + download
    )


def new_version_id() -> str:
    """Mint a fresh, opaque version id for a locally authored change.

    Consumers: ``hsync-client`` (``sync_state.note_local_edit``),
    ``hsync-server`` (``arbitration.py`` self-record), ``hsync-android``
    (``Version.newVersionId``).
    """
    return secrets.token_hex(_VERSION_ID_BYTES)


def compare_vclocks(a: dict[str, int] | None, b: dict[str, int] | None) -> VClockOrder:
    """Compare two vector clocks (absent ⇒ empty).

    ``a`` dominates ``b`` iff ``a[k] >= b[k]`` for every key ``k`` and the two
    differ. Returns :attr:`VClockOrder.concurrent` when neither dominates.

    Consumers: ``hsync-common`` (``resolve_three_way``, ``TombstoneStore.merge``),
    ``hsync-client`` (``sync._compare_files``), ``hsync-server``
    (``arbitration.py``) and ``hsync-android`` (``Version.compareVclocks`` mirror).
    """
    a = a or {}
    b = b or {}
    keys = a.keys() | b.keys()
    a_ge = all(a.get(k, 0) >= b.get(k, 0) for k in keys)
    b_ge = all(b.get(k, 0) >= a.get(k, 0) for k in keys)
    if a_ge and b_ge:
        return VClockOrder.equal
    if a_ge:
        return VClockOrder.dominates
    if b_ge:
        return VClockOrder.dominated
    return VClockOrder.concurrent


def tick_vclock(vclock: dict[str, int] | None, cid: str) -> dict[str, int]:
    """Return a copy of *vclock* with the author's own counter incremented.

    A node ticks its own counter exactly once per observed local edit, producing
    monotonically increasing clocks (``M:1`` → ``M:2``) so two distinct versions
    can never alias the same clock (the anti-aliasing invariant, §3.4.7 of
    ADR-0022). Absent foreign keys are preserved; ``vclock`` is never mutated.

    Consumers: ``hsync-client`` (``sync_state.note_local_edit``,
    ``local_version_for_compare``, upload version fields), ``hsync-server``
    (``arbitration.py`` self-record), ``TombstoneStore.record`` (deletion tick)
    and ``hsync-android`` (``Version.tickVclock`` mirror).
    """
    result = dict(vclock) if vclock else {}
    result[cid] = result.get(cid, 0) + 1
    return result


def merge_vclocks(a: dict[str, int] | None, b: dict[str, int] | None) -> dict[str, int]:
    """Return the componentwise maximum of two vector clocks.

    Used when recording the agreed version after a sync: the winner's clock
    includes both histories, so third nodes recognise either side as an ancestor
    and no false conflict propagates downstream. Also used to join concurrent
    tombstone clocks (ADR-0003).

    Consumers: ``hsync-client`` (``sync_state.merge_and_record``),
    ``hsync-server`` (``arbitration.py`` record clock), receiver-local record
    on accepted uploads, ``TombstoneStore`` and ``hsync-android``
    (``Version.mergeVclocks`` mirror).
    """
    a = a or {}
    b = b or {}
    return {k: max(a.get(k, 0), b.get(k, 0)) for k in a.keys() | b.keys()}


def parse_version_info(data: object) -> VersionInfo | None:
    """Tolerantly parse a wire ``version`` object into :class:`VersionInfo`.

    Returns ``None`` (treated as "no version advertised" ⇒ empty clock) on any
    structural violation, so a malformed or oversized payload never causes a
    protocol error — the caller's causal matrix handles an absent version
    natively. Consumers: ``hsync-server`` (upload form/listing), ``hsync-client``
    (remote decode), ``hsync-android`` (``FileInfo`` mirror).
    """
    if not isinstance(data, dict):
        return None
    raw_vclock = data.get("vclock")
    if not isinstance(raw_vclock, dict) or len(raw_vclock) > VCLOCK_MAX_ENTRIES:
        return None
    vclock: dict[str, int] = {}
    for key, value in raw_vclock.items():
        # bool is a subclass of int — reject it explicitly (a `True` counter
        # would silently parse as 1, masking a corrupt payload).
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        if not is_valid_cid(key):
            return None
        vclock[key] = value
    version_id = data.get("version_id")
    if not isinstance(version_id, str):
        version_id = ""
    origin_cid = data.get("origin_cid")
    if origin_cid is not None and not (isinstance(origin_cid, str) and is_valid_cid(origin_cid)):
        return None
    ts = _parse_wire_timestamp(data.get("ts", 0))
    if ts is None:
        return None
    result: VersionInfo = VersionInfo(
        vclock=vclock, version_id=version_id, origin_cid=origin_cid, ts=ts, corrected_mtime=0
    )
    raw_corrected = data.get("corrected_mtime")
    if raw_corrected is not None:
        if isinstance(raw_corrected, bool) or not isinstance(raw_corrected, (int, float)):
            # Tolerated like missing version metadata: an unknown/malformed
            # chronological field degrades to the deterministic hash fallback.
            return result
        parsed_corrected = _parse_wire_timestamp(raw_corrected)
        if parsed_corrected is not None:
            result["corrected_mtime"] = parsed_corrected
    return result


def resolve_three_way(
    local_hash: str | None,
    local_vclock: dict[str, int] | None,
    remote_hash: str | None,
    remote_vclock: dict[str, int] | None,
    base_hash: str | None,
    *,
    local_corrected_mtime: int = 0,
    remote_corrected_mtime: int = 0,
) -> SyncDecision:
    """Decide the sync direction from content hashes and causal vector clocks.

    The hash decides content identity; the vector clock decides causality. On a
    true causal divergence the **corrected mtime tie-break** decides the winner
    chronologically (ADR-0023): the higher ``*_corrected_mtime`` wins the
    original path. The raw wall clock is never consulted directly; when either
    side lacks a corrected mtime (``0``) or the two tie, the deterministic
    SHA-256 fallback decides so every peer still converges on the same winner.
    The matrix covers the *file-present-on-both-sides* case; callers handle
    absent-file (deletion) branches separately (causal tombstones, ADR-0003).

    Args:
        local_hash: SHA-256 of the local file (None if absent).
        local_vclock: stored local clock (always honest via self-record, §3.4.7
            of ADR-0022; None ⇒ empty).
        remote_hash: SHA-256 of the advertised remote file (None if absent).
        remote_vclock: advertised remote clock (None/absent on the wire ⇒ empty).
        base_hash: SHA-256 of the last-synced common ancestor (None if unknown).
        local_corrected_mtime: clock-offset-corrected mtime of the local
            version (0 ⇒ unknown; hash fallback applies).
        remote_corrected_mtime: clock-offset-corrected mtime of the remote
            version (0 ⇒ unknown; hash fallback applies).

    Returns:
        The :class:`SyncDecision`. ``conflict_*`` signals a true divergence
        (concurrent clocks, or no causal information either way with differing
        content): the corrected-mtime tie-break picks the winner and the loser
        is preserved as a conflict copy.

    Consumers: ``hsync-client`` (``sync._compare_files``,
    ``get_sync_actions``, realtime ``update_file``), ``hsync-server``
    (``arbitration.arbitrate_upload``, upload and delta-apply) and
    ``hsync-android`` (``Version.resolveThreeWay`` mirror).
    """
    if local_hash == remote_hash:
        return SyncDecision.in_sync
    if base_hash is not None:
        if local_hash == base_hash:
            # Local untouched since base, remote moved on -> take remote.
            return SyncDecision.download
        if remote_hash == base_hash:
            # Remote untouched since base, local moved on -> push local.
            return SyncDecision.upload
    order = compare_vclocks(local_vclock, remote_vclock)
    if order is VClockOrder.dominates:
        return SyncDecision.upload
    if order is VClockOrder.dominated:
        return SyncDecision.download
    # concurrent (or equal-clock-anomaly, or both-empty with differing content):
    # true divergence -> chronological corrected-mtime tie-break (ADR-0023),
    # with the deterministic SHA-256 fallback when a side lacks the field or
    # the two values tie.
    if local_corrected_mtime > 0 and remote_corrected_mtime > 0:
        if local_corrected_mtime > remote_corrected_mtime:
            return SyncDecision.conflict_upload
        if remote_corrected_mtime > local_corrected_mtime:
            return SyncDecision.conflict_download
    # fallback: highest SHA-256 lexicographically
    if (local_hash or "") > (remote_hash or ""):
        return SyncDecision.conflict_upload
    return SyncDecision.conflict_download


def _parse_stored_vclock(raw: object) -> dict[str, int] | None:
    """Parse a ``vclock`` read from local storage (validated as untrusted).

    A structurally invalid clock (non-dict, oversized, ``bool``/negative
    counters, non-cid keys, unknown-types) makes the whole entry unusable:
    the caller drops it rather than fabricating an empty clock, which could
    mask a corrupted common ancestor and flip a sync decision.
    """
    if not isinstance(raw, dict) or len(raw) > VCLOCK_MAX_ENTRIES:
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
