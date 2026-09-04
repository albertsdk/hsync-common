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
parser are re-exported from ``._util`` for the historic consumers. The
persistence layer (:class:`TombstoneStore`) lives in :mod:`.tombstone_store`
and is re-exported here for the historic import path.
"""

from typing import TypedDict, TypeGuard, cast

from hsync_common.hashing import is_sha256_hex

from ._util import _parse_wire_timestamp, relpath_in_bucket, tombstone_key
from .event import is_valid_cid
from .version import VClockOrder, compare_vclocks, parse_vclock

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


def _is_valid_key(key: object) -> TypeGuard[str]:
    """Return True when *key* looks like a sha256 hex digest (tombstone key).

    Tombstone keys are always `hashlib.sha256(...).hexdigest()` output, i.e.
    lowercase: uppercase variants from a peer are rejected (they would never
    match a locally computed key anyway).
    """
    return is_sha256_hex(key) and key == key.lower()


def _is_valid_sha256(value: object) -> TypeGuard[str | None]:
    """Return True when *value* is None or a sha256 hex digest."""
    return value is None or _is_valid_key(value)


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
    payload = cast(dict[str, object], entry)
    ts = _parse_wire_timestamp(payload["ts"])
    if ts is None or ts <= 0 or ts > now + TOMBSTONE_MAX_CLOCK_SKEW_SECONDS:
        return None
    sha = payload.get("sha256")
    if not _is_valid_sha256(sha):
        return None
    vclock = parse_vclock(payload.get("vclock"))
    if vclock is None:
        return None
    version_id = payload.get("version_id")
    if not isinstance(version_id, str):
        version_id = ""
    origin_cid = payload.get("origin_cid")
    if origin_cid is not None and not (isinstance(origin_cid, str) and is_valid_cid(origin_cid)):
        return None
    return TombstoneEntry(
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


# Re-export the SQLite-backed store for the historic import path
# (``from hsync_common.models.tombstone import TombstoneStore``). Imported last:
# ``tombstone_store`` imports the helpers above, so this module must be fully
# defined before the line below runs.
from .tombstone_store import TombstoneStore  # noqa: E402,F401
