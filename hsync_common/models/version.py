# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was distributed with this
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

On a true divergence (concurrent clocks) a deterministic, content-only tie-break
picks the winner (highest SHA-256 lexicographically) and the losing content is
preserved as a ``_conflicted_copy_`` (extrema ratio). No node is authoritative:
the server and the elected LAN master are transport hubs only; every node
applies the same algorithm (see ADR-0022).

The store mirrors :class:`hsync_common.models.tombstone.TombstoneStore`: a
hidden ``.hsyncstate`` side-car with atomic JSON persistence. It is private to
each peer and never exchanged; the wire form is :class:`VersionInfo`.
"""

import json
import secrets
import time
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

from .event import is_valid_cid
from .tombstone import _parse_wire_timestamp, relpath_in_bucket, tombstone_key

__all__ = [
    "FileVersion",
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
_VCLOCK_MAX_ENTRIES = 256


class FileVersion(TypedDict):
    """Recorded common-ancestor version for a single path (private, never exchanged).

    Consumers: ``hsync-client`` (``sync_state`` store wrapper), ``hsync-server``
    (``versions.py`` per-bucket stores), ``hsync-android`` (``Version.kt``
    ``SyncStateStore`` mirror).
    """

    base_hash: str  # content hash agreed on at the last successful sync
    version_id: str  # opaque id of that version (lineage, not content-derived)
    origin_cid: str | None  # peer that authored the version (None if unknown)
    ts: int  # wall-clock timestamp the base was recorded (unix seconds, informational only)
    vclock: dict[str, int]  # causal history: node cid -> logical counter


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


class VClockOrder(StrEnum):
    """Result of comparing two vector clocks.

    Consumers: ``hsync-common`` (``resolve_three_way``), ``hsync-client``
    (``sync._compare_files``) and ``hsync-android`` (``Version.kt`` mirror).
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


def _clock_value(vclock: dict[str, int] | None, cid: str) -> int:
    """Return the counter for *cid*, treating a missing clock/key as 0."""
    if not vclock:
        return 0
    return vclock.get(cid, 0)


def compare_vclocks(a: dict[str, int] | None, b: dict[str, int] | None) -> VClockOrder:
    """Compare two vector clocks (absent ⇒ empty).

    ``a`` dominates ``b`` iff ``a[k] >= b[k]`` for every key ``k`` and the two
    differ. Returns :attr:`VClockOrder.concurrent` when neither dominates.

    Consumers: ``hsync-common`` (``resolve_three_way``), ``hsync-client``
    (``sync._compare_files``), ``hsync-server`` (``arbitration.py``) and
    ``hsync-android`` (``Version.compareVclocks`` mirror).
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
    (``arbitration.py`` self-record) and ``hsync-android``
    (``Version.tickVclock`` mirror).
    """
    result = dict(vclock) if vclock else {}
    result[cid] = result.get(cid, 0) + 1
    return result


def merge_vclocks(a: dict[str, int] | None, b: dict[str, int] | None) -> dict[str, int]:
    """Return the componentwise maximum of two vector clocks.

    Used when recording the agreed version after a sync: the winner's clock
    includes both histories, so third nodes recognise either side as an ancestor
    and no false conflict propagates downstream.

    Consumers: ``hsync-client`` (``sync_state.merge_and_record``),
    ``hsync-server`` (``arbitration.py`` record clock), receiver-local record
    on accepted uploads and ``hsync-android`` (``Version.mergeVclocks`` mirror).
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
    if not isinstance(raw_vclock, dict) or len(raw_vclock) > _VCLOCK_MAX_ENTRIES:
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
    return VersionInfo(vclock=vclock, version_id=version_id, origin_cid=origin_cid, ts=ts)


def resolve_three_way(
    local_hash: str | None,
    local_vclock: dict[str, int] | None,
    remote_hash: str | None,
    remote_vclock: dict[str, int] | None,
    base_hash: str | None,
) -> SyncDecision:
    """Decide the sync direction from content hashes and causal vector clocks.

    The hash decides content identity; the vector clock decides causality; the
    wall clock is never consulted. The matrix covers the *file-present-on-both-
    sides* case; callers handle absent-file (deletion) branches separately
    (tombstones, ADR-0019).

    Args:
        local_hash: SHA-256 of the local file (None if absent).
        local_vclock: stored local clock (always honest via self-record, §3.4.7
            of ADR-0022; None ⇒ empty).
        remote_hash: SHA-256 of the advertised remote file (None if absent).
        remote_vclock: advertised remote clock (None/absent on the wire ⇒ empty).
        base_hash: SHA-256 of the last-synced common ancestor (None if unknown).

    Returns:
        The :class:`SyncDecision`. ``conflict_*`` signals a true divergence
        (concurrent clocks, or no causal information either way with differing
        content): the deterministic tie-break picks the winner by highest hash
        and the loser is preserved as a conflict copy.

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
    # true divergence -> deterministic content-only tie-break.
    if (local_hash or "") > (remote_hash or ""):
        return SyncDecision.conflict_upload
    return SyncDecision.conflict_download


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
        version_id: str | None = None,
        origin_cid: str | None = None,
        timestamp: int | float | None = None,
        vclock: dict[str, int] | None = None,
    ) -> None:
        """Record (overwrite) the agreed base version for a relative path."""
        ts = int(timestamp) if timestamp is not None else int(time.time())
        self._data[tombstone_key(relpath)] = FileVersion(
            base_hash=base_hash,
            version_id=version_id or new_version_id(),
            origin_cid=origin_cid,
            ts=ts,
            vclock=dict(vclock) if vclock else {},
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
    def load(self) -> None:
        """Load recorded versions from the backing JSON file, if present.

        Tolerates side-cars written before vector clocks existed: an entry
        without ``vclock`` loads with an empty clock (the ``base_hash`` fast
        paths of :func:`resolve_three_way` remain valid).
        """
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
        if not isinstance(entries, dict):
            # A malformed side-car (e.g. "versions" is a list) must not crash
            # startup — treat it as empty.
            return
        data: dict[str, FileVersion] = {}
        for key, entry in entries.items():
            if not isinstance(entry, dict) or "base_hash" not in entry:
                continue
            ts = _parse_wire_timestamp(entry.get("ts", 0))
            if ts is None:
                continue
            vclock = _parse_stored_vclock(entry.get("vclock"))
            data[key] = FileVersion(
                base_hash=str(entry["base_hash"]),
                version_id=str(entry.get("version_id", "")),
                origin_cid=entry.get("origin_cid"),
                ts=ts,
                vclock=vclock,
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


def _parse_stored_vclock(raw: object) -> dict[str, int]:
    """Parse a ``vclock`` read from the local side-car (trusted, but validated).

    Unlike :func:`parse_version_info` (untrusted wire input) this trusts the
    local store's own data but still drops structurally-invalid entries so a
    hand-edited side-car degrades entry-by-entry rather than crashing.
    """
    if not isinstance(raw, dict):
        return {}
    vclock: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            continue
        vclock[str(key)] = value
    return vclock
