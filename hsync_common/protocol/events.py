# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Structured UI-event contract emitted by the client over ``--events-json-fd``.

This is the single source of truth for the JSON-Lines status channel that
replaces the Desktop's fragile log-regex parsing.
Each line on the events fd is one JSON object validated against this schema:
a ``schema_version``, an ISO-8601 ``ts``, an ``event`` discriminator and a flat
set of optional payload fields (only the ones relevant to the event are set).

The mapping is 1:1 with the signals the Desktop ``engine`` exposes, so the GUI
consumes structured events instead of matching log wording. The text log stays
purely diagnostic.

Each per-file status burst is bracketed by one marker pair: ``preview_start`` /
``preview_end`` around the comparison a front-end requested, ``status_pass_start``
/ ``status_pass_end`` around the classification pass of the device that serves
the share. A consumer therefore never has to infer the end of a burst, and a
serving pass can never confirm a pending sync. A serving pass also carries one
``device_status`` row per live device, so a consumer reports a per-device verdict
(worst case plus attribution) instead of a union that hides which device lags.

A preview additionally reports the two facts only the client knows:
``preview_skipped`` (deletions the policy drops before they reach the stream) and
``preview_warning`` (a plan the mass-deletion guard will pause). A front-end
never infers either: a plan with no ``to_delete`` row can mean "nothing to delete"
or "deletions kept", and the two need different wording.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, NotRequired, TypedDict

from hsync_common.time_utils import utc_now_iso

__all__ = [
    "EVENTS_SCHEMA_VERSION",
    "UiEventDict",
    "UiEventName",
    "build_event",
    "parse_event_line",
    "serialize_event",
]

# The only accepted event schema version. A mismatching value is rejected
# outright instead of being interpreted.
EVENTS_SCHEMA_VERSION = 1


class UiEventName(StrEnum):
    """Discriminator for a structured UI event (1:1 with Desktop signals)."""

    status = "status"  # connection status: disconnected|connecting|connected|waiting|error
    ready = "ready"  # startup validation passed; the engine is entering its run loop
    peers = "peers"  # client presence changed (connected / total clients in the share)
    role = "role"  # this client became master / client
    bucket = "bucket"  # bucket name detected
    group = "group"  # p2p group name detected
    discovery = "discovery"  # active discovery plan(s) ("mdns" | "mdns+bootnode") at startup
    session = "session"  # session CID established
    server = "server"  # server / master URL detected
    transfer = "transfer"  # a file was downloaded / uploaded / deleted
    rename = "rename"  # a file or directory was renamed
    dir_created = "dir_created"  # a directory was created
    progress = "progress"  # in-flight transfer progress (op: download|upload)
    # a full sync cycle finished; carries the per-action counters
    # (downloaded/uploaded/deleted/renamed/skipped/failed/conflicts)
    sync_complete = "sync_complete"
    folder_size = "folder_size"  # local bytes + sync-set total (aggregate, per cycle)
    error = "error"  # generic error
    # A non-fatal condition the user must eventually see (a degraded watcher, an
    # unreachable bootnode). Distinct from ``error``: the run continues, so the
    # front-end surfaces it as a warning and must not treat it as a failure.
    warning = "warning"
    auth_error = "auth_error"  # authentication error (invalid/missing API key)
    path_not_found = "path_not_found"  # shared path does not exist
    master_conflict = "master_conflict"  # master conflict / takeover
    no_master = "no_master"  # no master elected (all peers never-master)
    no_peers = "no_peers"  # a p2p one-shot aborted: no peer discovered
    sync_pending = (
        "sync_pending"  # classification not possible yet: reason=no_device|awaiting_inventory
    )
    preview_start = "preview_start"  # dry-run preview scan started
    preview_end = "preview_end"  # dry-run preview scan ended
    # The serving side's own pass: a p2p master compares the share it holds with
    # the inventories the devices published. A distinct pair, so a classification
    # never consumes the preview above (only preview_end may confirm a sync).
    status_pass_start = "status_pass_start"  # serving-side classification started
    status_pass_end = "status_pass_end"  # serving-side classification ended
    # One row per live device inside a serving pass: what that device still
    # lacks (pending_there), what it holds and the share does not (pending_here)
    # and how many identities it published (held). The serving device renders a
    # per-device verdict from these instead of a single union aggregate.
    device_status = "device_status"
    # The preview plan the front-end cannot derive by itself: deletions the
    # configured policy drops before they reach the event stream (reason=
    # "deletion_policy", count, size) and a plan the mass-deletion guard will
    # pause (reason="mass_delete_guard", deletes, local).
    preview_skipped = "preview_skipped"
    preview_warning = "preview_warning"
    file_status = "file_status"  # preview per-file status (synced/to_*)
    rename_status = "rename_status"  # preview rename status
    # ── LAN security ─────────────────────────────────────────────────
    fingerprint_changed = "fingerprint_changed"  # pinned master cert changed (TOFU)
    auth_required = "auth_required"  # a shared LAN key is required but missing
    pairing_needed = "pairing_needed"  # an explicit trust confirmation is required
    duplicate_identity = "duplicate_identity"  # two live hosts present the same device ID
    # ── Transfer resilience ─────────────────────────────────────────
    transfer_failed = "transfer_failed"  # a file transfer gave up after retries
    # ── Mass-deletion guard ─────────────────────────────────────────
    sync_paused = "sync_paused"  # a safety guard paused part of a sync cycle
    # ── Conflict resolution ─────────────────────────────────────────
    conflict_resolved = (
        "conflict_resolved"  # both sides diverged; master won, local saved as conflicted copy
    )
    # ── Inbound path security ───────────────────────────────────────
    security_rejected = "security_rejected"  # unsafe remote path rejected


class UiEventDict(TypedDict):
    """Type-safe shape of a single serialized UI event line."""

    schema_version: int
    ts: str
    event: str
    # ── optional payload (only the fields relevant to ``event`` are present) ──
    status: NotRequired[str]
    connected: NotRequired[int]  # peers event: clients currently connected (self included)
    is_master: NotRequired[bool]
    bucket: NotRequired[str]
    group: NotRequired[str]
    cid: NotRequired[str]
    url: NotRequired[str]
    op: NotRequired[str]  # transfer/progress direction: download|upload|...
    file: NotRequired[str]
    size: NotRequired[int]
    src: NotRequired[str]
    dst: NotRequired[str]
    path: NotRequired[str]
    transferred: NotRequired[int]
    total: NotRequired[int]  # peers event (clients in the share) / progress event (bytes)
    message: NotRequired[str]
    conflict_type: NotRequired[str]
    peer_cid: NotRequired[str]
    peer_address: NotRequired[str]
    state: NotRequired[str]
    elapsed: NotRequired[int]
    fingerprint: NotRequired[str]
    # fingerprint_changed / pairing_needed: "master" | "bootnode" | "server"
    scope: NotRequired[str]
    conflict_copy: NotRequired[str]  # path of the preserved local copy (conflict_resolved)
    winner: NotRequired[str]  # which side won: "remote" (master) or "local"
    source_cid: NotRequired[str]  # verified peer source for a successful full-file transfer
    # warning: stable identifier of the subsystem that reported it ("bootnode",
    # "watcher", …). The front-end keys its dedup and its notification category
    # on it, so it is an identifier, never a user-facing sentence.
    source: NotRequired[str]
    # warning: how much of a bounded resource the condition needs versus the
    # maximum in force (inotify watches, open descriptors). Numbers, not text, so
    # a front-end can localize "needs N, limit M" and name the right remedy.
    needed: NotRequired[int]
    limit: NotRequired[int]
    reason: NotRequired[str]  # sync_paused: human-readable guard reason
    # device_status: the device's backlog against the share it is compared with.
    pending_here: NotRequired[int]  # identities the device holds, missing here
    pending_there: NotRequired[int]  # local identities the device does not hold
    held: NotRequired[int]  # identities the device published
    # file_status: how many live devices hold this identity out of ``devices``.
    holders: NotRequired[int]
    # device_status / file_status / sync_pending: live devices compared.
    devices: NotRequired[int]
    # sync_pending: connected devices whose inventory has not been published yet.
    expected: NotRequired[int]
    # preview_skipped: actions the plan dropped before emitting them.
    count: NotRequired[int]
    deletes: NotRequired[int]  # sync_paused: deletions blocked this cycle
    local: NotRequired[int]  # sync_paused: local files considered by the guard
    local_bytes: NotRequired[int]  # folder_size: files present on this device
    total_bytes: NotRequired[int]  # folder_size: remote listing + local-only files
    plan: NotRequired[str]  # discovery event: "mdns" | "mdns+bootnode"
    bootnode: NotRequired[str]  # discovery event: bootnode host (empty without one)
    # sync_complete: what the cycle applied, reported by the engine itself (a
    # rename or delete moves no bytes, so the byte-transfer events cannot
    # describe the outcome).
    downloaded: NotRequired[int]
    uploaded: NotRequired[int]
    deleted: NotRequired[int]
    renamed: NotRequired[int]
    skipped: NotRequired[int]
    failed: NotRequired[int]
    conflicts: NotRequired[int]


def build_event(
    event: UiEventName | str,
    *,
    ts: str | None = None,
    **payload: Any,
) -> UiEventDict:
    """Assemble a versioned event dict, dropping ``None`` payload values.

    Args:
        event: The event discriminator (enum member or its string value).
        ts: ISO-8601 timestamp; the current UTC time is used when omitted.
        **payload: Event-specific fields (see :class:`UiEventDict`).
    """
    out: dict[str, Any] = {
        "schema_version": EVENTS_SCHEMA_VERSION,
        "ts": ts or utc_now_iso(),
        "event": str(event),
    }
    out.update({k: v for k, v in payload.items() if v is not None})
    return out  # type: ignore[return-value]


def serialize_event(event: UiEventDict) -> str:
    """Serialize an event to a compact single-line JSON string (no newline)."""
    return json.dumps(event, separators=(",", ":"), ensure_ascii=False)


def parse_event_line(line: str) -> UiEventDict | None:
    """Parse and validate one event line.

    Returns ``None`` for blank lines, malformed JSON, non-object payloads, a
    missing ``event`` field, or an unsupported ``schema_version`` — the caller
    treats any of these as "not an event" and ignores the line.
    """
    text = line.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != EVENTS_SCHEMA_VERSION:
        return None
    if not data.get("event"):
        return None
    return data  # type: ignore[return-value]
