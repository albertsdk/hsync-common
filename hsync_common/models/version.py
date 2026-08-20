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

The persistence layer (:class:`SyncStateStore`) lives in
:mod:`.version_store` and is re-exported here for the historic import path;
the wire form is :class:`VersionInfo`.
"""

import secrets
from enum import StrEnum
from typing import TypedDict

from ._util import _parse_wire_timestamp, relpath_in_bucket
from .event import is_valid_cid

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
    "parse_vclock",
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


def parse_vclock(raw: object) -> dict[str, int] | None:
    """Strictly parse a vector clock from an untrusted payload or storage row.

    Returns ``None`` on any structural violation: a non-dict clock, more than
    ``VCLOCK_MAX_ENTRIES`` entries, ``bool`` or negative counters, or non-CID
    keys. An explicitly empty ``{}`` is a valid clock (it carries no causal
    information and is dominated by any non-empty one).

    Consumers: ``parse_version_info`` (wire), ``TombstoneStore`` /
    ``SyncStateStore`` (storage load), ``hsync-android`` mirror.
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
    vclock = parse_vclock(raw_vclock)
    if vclock is None:
        return None
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


# Re-export the SQLite-backed store for the historic import path
# (``from hsync_common.models.version import SyncStateStore``). Imported last:
# ``version_store`` imports the pure helpers above, so this module must be fully
# defined before the line below runs.
from .version_store import SyncStateStore  # noqa: E402,F401
