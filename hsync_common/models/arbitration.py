# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Causal upload arbitration shared by the sync server and the P2P master.

The receiver of an upload is a transport hub, not an authority (ADR-0022): every
incoming version is compared causally against the version last stored for the
path, and the result tells the caller whether to write the incoming bytes,
reject them as stale, or preserve them as a conflicted copy.

The module is persistence-free: each consumer reads its own store (per-bucket on
the server, per-folder on the client), applies :func:`plan_self_record` when the
file on disk drifted behind the stored base, then passes the resulting record to
:func:`decide_arbitration`. Keeping the decision here is what makes the server
and the elected LAN master byte-for-byte equivalent; only the store/CID binding
stays project-specific.

Consumers: ``hsync-server`` (``arbitration.py``: REST upload and delta apply),
``hsync-client`` (``arbitration.py``: P2P master uploads), shared tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .version import (
    FileVersion,
    SyncDecision,
    merge_vclocks,
    parse_version_info,
    resolve_three_way,
    tick_vclock,
)

__all__ = [
    "ArbitrationOutcome",
    "ArbitrationResult",
    "SelfRecord",
    "conflicted_copy_name",
    "decide_arbitration",
    "plan_self_record",
]


class ArbitrationOutcome(StrEnum):
    """Outcome of arbitrating an incoming upload against the stored version."""

    accepted = "accepted"  # incoming is causally ahead or at parity: write it
    accepted_conflict_won = "accepted_conflict_won"  # concurrent: incoming wins tie-break
    superseded = "superseded"  # incoming is causally dominated (stale): reject, no copy
    conflict_lost = "conflict_lost"  # concurrent: incoming loses tie-break: preserve it


@dataclass(frozen=True)
class ArbitrationResult:
    """Result of causal arbitration for an upload.

    ``record_vclock`` is the clock the receiver should record on accept
    (``merge_vclocks(incoming_vclock, stored_vclock)`` per the convergence
    invariant, ADR-0022 §5).
    ``record_corrected_mtime`` is the corrected mtime (ADR-0023) the receiver
    records alongside: the incoming value on accept, the stored value on
    reject, 0 when unknown.
    ``loser_cid`` is the author of the losing content for conflict-copy naming.
    """

    outcome: ArbitrationOutcome
    record_vclock: dict[str, int]
    record_corrected_mtime: int = 0
    loser_cid: str | None = None


@dataclass(frozen=True)
class SelfRecord:
    """Version advance to persist for an out-of-band edit of the stored base."""

    base_hash: str
    vclock: dict[str, int]


def plan_self_record(
    stored: FileVersion | None,
    disk_hash: str | None,
    cid: str | None,
) -> SelfRecord | None:
    """Return the self-record advance an out-of-band edit requires, if any.

    A write the receiver did not observe leaves the stored ``base_hash`` behind
    the file on disk; recording that content under the receiver's own cid before
    comparing keeps its clock honest (anti-aliasing invariant, ADR-0022 §3.4.7).

    Returns ``None`` when there is nothing to record: no stored version, unknown
    disk content, content already equal to the base, or no cid to attribute the
    edit to.
    """
    if stored is None or disk_hash is None or not cid:
        return None
    if stored["base_hash"] == disk_hash:
        return None
    return SelfRecord(base_hash=disk_hash, vclock=tick_vclock(stored["vclock"], cid))


def decide_arbitration(
    *,
    stored: FileVersion | None,
    incoming_hash: str,
    incoming_vclock_raw: object,
    incoming_version_id: str,
    incoming_origin_cid: str | None,
    incoming_corrected_mtime: int = 0,
) -> ArbitrationResult:
    """Decide what to do with an incoming version compared to the stored one.

    Args:
        stored: The stored version for the path after any self-record advance,
            or ``None`` when the path has no recorded version.
        incoming_hash: SHA-256 of the incoming content.
        incoming_vclock_raw: Raw parsed ``vclock`` payload (validated here).
        incoming_version_id: Version id from the uploader.
        incoming_origin_cid: Origin cid from the uploader (may be None).
        incoming_corrected_mtime: ADR-0023 corrected mtime advertised by the
            uploader (0 ⇒ unknown ⇒ the hash fallback applies).

    Returns:
        The :class:`ArbitrationResult`; the caller writes the file / conflicted
        copy / response based on ``outcome`` and records ``record_vclock`` on
        accept.
    """
    stored_hash = stored["base_hash"] if stored else None
    stored_vclock = stored["vclock"] if stored else None

    # Parse the incoming wire vclock tolerantly (malformed ⇒ empty clock).
    incoming_info = parse_version_info(
        {
            "vclock": incoming_vclock_raw,
            "version_id": incoming_version_id,
            "origin_cid": incoming_origin_cid,
            "ts": 0,
        }
    )
    incoming_vclock = incoming_info["vclock"] if incoming_info else {}
    effective_origin = incoming_info["origin_cid"] if incoming_info else incoming_origin_cid

    stored_corrected_mtime = int(stored.get("corrected_mtime", 0) or 0) if stored else 0
    decision = resolve_three_way(
        incoming_hash,
        incoming_vclock,
        stored_hash,
        stored_vclock,
        None,  # no base_hash: the receiver compares incoming vs stored directly
        # (the base-identity fast paths are a client-side concern; the receiver
        # has no independent knowledge of the common ancestor beyond the stored
        # version, which is already one of the two sides here).
        local_corrected_mtime=incoming_corrected_mtime,
        remote_corrected_mtime=stored_corrected_mtime,
    )

    match decision:
        case SyncDecision.in_sync:
            # Identical content already on disk: no-op accept (caller may 409 dup).
            return ArbitrationResult(
                outcome=ArbitrationOutcome.accepted,
                record_vclock=merge_vclocks(incoming_vclock, stored_vclock),
                record_corrected_mtime=incoming_corrected_mtime or stored_corrected_mtime,
            )
        case SyncDecision.upload:
            # Incoming causally ahead (or stored at base): accept.
            return ArbitrationResult(
                outcome=ArbitrationOutcome.accepted,
                record_vclock=merge_vclocks(incoming_vclock, stored_vclock),
                record_corrected_mtime=incoming_corrected_mtime,
            )
        case SyncDecision.download:
            # Stored dominates incoming: the upload is stale (an ancestor).
            return ArbitrationResult(
                outcome=ArbitrationOutcome.superseded,
                record_vclock=stored_vclock or {},
                record_corrected_mtime=stored_corrected_mtime,
                loser_cid=None,
            )
        case SyncDecision.conflict_upload:
            # Incoming wins the tie-break ⇒ accept, preserve the stored loser.
            loser_cid = (
                stored["origin_cid"] if stored and stored["origin_cid"] else effective_origin
            )
            return ArbitrationResult(
                outcome=ArbitrationOutcome.accepted_conflict_won,
                record_vclock=merge_vclocks(incoming_vclock, stored_vclock),
                record_corrected_mtime=incoming_corrected_mtime,
                loser_cid=loser_cid,
            )
        case _:
            # conflict_download: incoming loses ⇒ reject, preserve the incoming loser.
            return ArbitrationResult(
                outcome=ArbitrationOutcome.conflict_lost,
                record_vclock=stored_vclock or {},
                record_corrected_mtime=stored_corrected_mtime,
                loser_cid=effective_origin,
            )


def conflicted_copy_name(file_location: str, cid: str | None, ts: str) -> str:
    """Build the canonical conflicted-copy path for a losing content.

    ``<stem>_conflicted_copy_<ts>_<cid>.<ext>`` (ADR-0021).
    """
    safe_cid = "".join(c for c in (cid or "unknown") if c.isalnum() or c in "-_.")[:32] or "unknown"
    path = Path(file_location)
    return f"{path.parent}/{path.stem}_conflicted_copy_{ts}_{safe_cid}{path.suffix}"
