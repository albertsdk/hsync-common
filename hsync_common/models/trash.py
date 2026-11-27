# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Sync trash: the record of one deleted file and the store's on-disk layout.

A deletion applied by the sync engine moves the bytes into a **device-local**
store under the installation state dir instead of unlinking them, so the file
stays recoverable (ADR-0056). The store never travels on the wire: the deletion
itself is still advertised as a causal tombstone (ADR-0003), which is exactly
what makes a restore converge — the restored content is a new version whose
clock supersedes the marker, so every peer resurrects the path.

Layout, under the trash root::

    <folder id>/<entry id>/entry.json          this record
    <folder id>/<entry id>/payload/<relpath>   the bytes, at their bucket path

``entry.json`` is the only shared contract: a front-end reads it through the
client's ``hsync trash list --json`` instead of re-deriving the layout.

Consumers: ``hsync-client`` (``hsync_client/trash.py`` store), ``hsync-desktop``
and ``hsync-android`` (JSON listing), shared fixtures/tests.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, cast

from hsync_common.constants import (
    TRASH_DIR_ENV,
    TRASH_DIRNAME,
    TRASH_ENTRY_FILENAME,
    TRASH_PAYLOAD_DIRNAME,
    TRASH_RESTORING_SUFFIX,
)
from hsync_common.defaults import (
    TRASH_MAX_SIZE_MB_DEFAULT,
    TRASH_QUOTA_FLOOR_MB_DEFAULT,
    TRASH_QUOTA_PERCENT_DEFAULT,
    TRASH_RETENTION_DAYS_DEFAULT,
    TRASH_RETENTION_DAYS_MAX,
)
from hsync_common.hashing import is_lower_sha256_hex
from hsync_common.state_paths import state_path

__all__ = [
    "TRASH_ENTRY_FILENAME",
    "TRASH_ORIGINS",
    "TRASH_ORIGIN_SYNC",
    "TRASH_ORIGIN_USER",
    "TRASH_PAYLOAD_DIRNAME",
    "TRASH_RESTORE_ALL_STATUSES",
    "TRASH_RESTORE_STATUSES",
    "TRASH_SWEEP_INTERVAL_SECONDS",
    "TRASH_UNRECOVERABLE_RESTORE",
    "TREE_TRASH_MAX_BYTES",
    "TREE_TRASH_MAX_FILES",
    "TrashEntry",
    "TrashSweepEntry",
    "TrashSweepPlan",
    "build_trash_contract",
    "entry_dir",
    "entry_payload_path",
    "is_safe_entry_id",
    "is_safe_folder_id",
    "is_safe_relpath",
    "parse_trash_entry",
    "plan_trash_sweep",
    "trash_folder_dir",
    "trash_root",
    "trash_root_inside_folder",
]

# Why the file was trashed: the sync engine applied a deletion, or the user
# removed it through a front-end. Both end up in the same store so one restore
# path covers them.
TRASH_ORIGIN_SYNC = "sync"
TRASH_ORIGIN_USER = "user"
TRASH_ORIGINS = (TRASH_ORIGIN_SYNC, TRASH_ORIGIN_USER)

# ``<unix seconds>-<hex>``: sorts by age as a string (the hex starts with the
# creation timestamp in nanoseconds), which the listing and the sweep rely on.
_ENTRY_ID_RE = re.compile(r"^[0-9]{10,}-[0-9a-f]{8,32}$")
# ``.hsyncfolder`` holds a UUIDv4; the store also accepts any bounded token so a
# hand-created marker cannot escape the root.
_FOLDER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# ── cross-language contract ───────────────────────────────────────────────────
# The values, patterns and case verdicts below are reproduced by every front-end
# and published as the committed fixture ``trash-contract`` (built by
# [build_trash_contract]): the Android parity test asserts its own constants and
# parsers against it, so changing one of these is a change to four components in
# the same task.

# A recursive delete parks the files it removes, but only up to these bounds: a
# tree of a hundred thousand files would otherwise hash gigabytes on the delete
# path. What is left behind is reported, never dropped silently.
TREE_TRASH_MAX_FILES = 1000
TREE_TRASH_MAX_BYTES = 1024**3  # 1 GiB

# How often a running sync may sweep the store (``TrashStore.prune_if_due``).
TRASH_SWEEP_INTERVAL_SECONDS = 3600

# Verdicts one restore reports (``RestoreReport.status``, ``hsync trash restore``).
TRASH_RESTORE_STATUSES = frozenset(
    {
        "restored",
        "disabled",
        "download-only",
        "no-entry",
        "destination-exists",
        "payload-missing",
        "payload-corrupt",
        "failed",
    }
)
# Refusals where the entry itself is unusable (the bytes are gone or do not match
# the record): unlike "destination-exists" or "download-only", retrying cannot
# succeed. This is the line a restore-all draws between skipped and failed.
TRASH_UNRECOVERABLE_RESTORE = frozenset({"payload-missing", "payload-corrupt", "failed"})
# Aggregate status of a restore-all that ran (``RestoreAllReport.status``).
TRASH_RESTORE_ALL_STATUSES = frozenset({"ok", "disabled"})


class TrashEntry(TypedDict):
    """Serialized record of one trashed file (``entry.json``, ADR-0056).

    Consumers: ``hsync-client`` (store), ``hsync-desktop`` / ``hsync-android``
    (read through ``hsync trash list --json``), shared tests.
    """

    relpath: str  # bucket-relative path, POSIX separators
    sha256: str  # content hash of the trashed bytes
    size: int  # bytes
    mtime_ns: int  # mtime of the file when it was trashed
    mode: int  # permission bits; 0 where the platform does not represent them
    deleted_at: int  # unix seconds
    origin: str  # one of TRASH_ORIGINS
    cid: str | None  # device that applied the deletion
    bucket: str  # share name the file belonged to


def is_safe_relpath(relpath: object) -> bool:
    """True when *relpath* is a plain bucket-relative POSIX path.

    Rejects absolute paths, drive letters, ``..`` components, backslashes, NUL
    and empty components: an entry's payload path is derived from it, so a
    crafted ``entry.json`` must never be able to reach outside the store.
    """
    if not isinstance(relpath, str) or not relpath or "\x00" in relpath:
        return False
    if relpath.startswith(("/", "\\")) or "\\" in relpath:
        return False
    if len(relpath) > 1 and relpath[1] == ":":
        return False
    if relpath.startswith("./") or relpath.endswith("/"):
        return False
    return all(part not in ("", ".", "..") for part in relpath.split("/"))


def is_safe_folder_id(folder_id: object) -> bool:
    """True when *folder_id* can name a directory directly under the root."""
    return isinstance(folder_id, str) and _FOLDER_ID_RE.match(folder_id) is not None


def is_safe_entry_id(entry_id: object) -> bool:
    """True when *entry_id* looks like an id this store minted."""
    return isinstance(entry_id, str) and _ENTRY_ID_RE.match(entry_id) is not None


def trash_root(directory: str | Path | None = None) -> Path:
    """Return the trash root: *directory*, else ``HSYNC_TRASH_DIR``, else state.

    The default lives under the installation state dir (ADR-0025), never inside
    a synced folder, so no peer sees it and no ignore rule has to hide it.
    Consumers: ``hsync-client`` (store, CLI), tests.
    """
    if directory is not None and str(directory).strip():
        return Path(directory).expanduser()
    return state_path(TRASH_DIRNAME, override_env=TRASH_DIR_ENV)


def trash_root_inside_folder(root: str | Path, folder: str | Path) -> bool:
    """True when *root* would place the store inside the synced *folder*.

    The store is device-local (ADR-0056): inside the folder its bytes are shared
    with the peers and re-uploaded on every cycle, which is the one thing this
    layout must never do. Callers refuse the layout instead of degrading it
    silently.

    Consumers: ``hsync-client`` (CLI validation and the cycle's store builder).
    """
    try:
        candidate = Path(root).expanduser().resolve()
        target = Path(folder).expanduser().resolve()
    except OSError:  # pragma: no cover - unresolvable path: let the store decide
        return False
    return candidate == target or target in candidate.parents


def trash_folder_dir(root: Path, folder_id: str) -> Path:
    """Return one folder's trash directory, refusing an unsafe folder id."""
    if not is_safe_folder_id(folder_id):
        raise ValueError(f"unsafe folder id for the trash store: {folder_id!r}")
    return root / folder_id


def entry_dir(root: Path, folder_id: str, entry_id: str) -> Path:
    """Return one entry's directory, refusing an unsafe entry id."""
    if not is_safe_entry_id(entry_id):
        raise ValueError(f"unsafe trash entry id: {entry_id!r}")
    return trash_folder_dir(root, folder_id) / entry_id


def entry_payload_path(entry: Path | str, relpath: str) -> Path:
    """Return the payload path of *relpath* inside *entry*, verified contained.

    Raises:
        ValueError: the relpath is unsafe or resolves outside the entry.
    """
    if not is_safe_relpath(relpath):
        raise ValueError(f"unsafe trash relpath: {relpath!r}")
    base = Path(entry) / TRASH_PAYLOAD_DIRNAME
    candidate = base / relpath
    normalised = Path(os.path.normpath(str(candidate)))
    if normalised != candidate:
        raise ValueError(f"unsafe trash relpath: {relpath!r}")
    return candidate


def _as_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _as_int(payload: dict[str, object], key: str, *, minimum: int = 0) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def parse_trash_entry(payload: object) -> TrashEntry | None:
    """Validate an ``entry.json`` payload read from disk.

    A damaged or hand-edited entry is skipped rather than trusted: every field
    the restore needs (path, content hash, size) must be structurally valid, and
    the relpath must be safe. Returns ``None`` when the payload is unusable.

    Consumers: ``hsync-client`` (store listing and restore), tests.
    """
    if not isinstance(payload, dict):
        return None
    data = cast(dict[str, object], payload)
    relpath = _as_str(data, "relpath")
    sha256 = _as_str(data, "sha256")
    # An absent origin is a record written before the field existed (``sync``);
    # a present but non-canonical one is damage, not something to guess at.
    raw_origin = data.get("origin")
    if raw_origin is None:
        origin = TRASH_ORIGIN_SYNC
    elif isinstance(raw_origin, str) and raw_origin in TRASH_ORIGINS:
        origin = raw_origin
    else:
        return None
    if not is_safe_relpath(relpath) or not is_lower_sha256_hex(sha256):
        return None
    size = _as_int(data, "size")
    deleted_at = _as_int(data, "deleted_at", minimum=1)
    if size is None or deleted_at is None:
        return None
    mtime_ns = _as_int(data, "mtime_ns")
    mode = _as_int(data, "mode")
    cid = data.get("cid")
    return TrashEntry(
        relpath=relpath,
        sha256=sha256,
        size=size,
        mtime_ns=mtime_ns or 0,
        mode=mode or 0,
        deleted_at=deleted_at,
        origin=origin,
        cid=cid if isinstance(cid, str) and cid else None,
        bucket=_as_str(data, "bucket"),
    )


# ── published contract ────────────────────────────────────────────────────────

# How many seconds a day the retention window is measured in.
_SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class TrashSweepEntry:
    """One stored entry as the sweep sees it (the rules ignore the bytes)."""

    entry_id: str
    deleted_at: int
    size: int


@dataclass(frozen=True)
class TrashSweepPlan:
    """What a retention/budget sweep drops, decided without touching a disk."""

    expired: tuple[str, ...]
    evicted: tuple[str, ...]
    kept: int
    freed: int


def plan_trash_sweep(
    entries: Sequence[TrashSweepEntry],
    *,
    retention_days: int,
    budget: int,
    now: int,
) -> TrashSweepPlan:
    """Decide which entries a sweep drops: the retention window, then the budget.

    This is the one declaration of the rule: ``hsync-client`` applies the plan to
    a real tree (``hsync_client/trash.py::prune_store``) instead of re-deriving
    it, and the ``prune_cases`` of the ``trash-contract`` fixture publish the same
    outcomes so the Android mirror
    (``TrashStore.pruneRoot``) is asserted against them.

    ``retention_days`` 0 disables the window; ``budget`` 0 disables eviction.
    Eviction is oldest-first, and two entries deleted in the same second are
    ordered by the entry id's fixed-width nanosecond field, so the tie-break
    follows creation order rather than chance.

    Consumers: ``hsync-client`` (store and ``hsync trash prune``),
    ``hsync-android`` (parity test), ``hsync-desktop`` / ``hsync-wd-os5`` through
    the client.
    """
    cutoff = now - retention_days * _SECONDS_PER_DAY
    expired = [
        entry.entry_id for entry in entries if retention_days > 0 and entry.deleted_at < cutoff
    ]
    dropped = set(expired)
    freed = sum(entry.size for entry in entries if entry.entry_id in dropped)
    survivors = [entry for entry in entries if entry.entry_id not in dropped]
    evicted: list[str] = []
    if budget > 0:
        total = sum(entry.size for entry in survivors)
        if total > budget:
            for entry in sorted(
                survivors, key=lambda survivor: (survivor.deleted_at, survivor.entry_id)
            ):
                if total <= budget:
                    break
                total -= entry.size
                freed += entry.size
                evicted.append(entry.entry_id)
    return TrashSweepPlan(
        expired=tuple(expired),
        evicted=tuple(evicted),
        kept=len(survivors) - len(evicted),
        freed=freed,
    )


# A record every front-end must accept, at its bucket path, with the fields a
# restore needs plus the optional metadata at their written values.
_CONTRACT_RECORD: dict[str, object] = {
    "relpath": "docs/report.pdf",
    "sha256": "a" * 64,
    "size": 42,
    "mtime_ns": 1_700_000_000_000_000_000,
    "mode": 0o644,
    "deleted_at": 1_700_000_100,
    "origin": TRASH_ORIGIN_SYNC,
    "cid": "DeviceCid123456",
    "bucket": "team",
}

_RELPATH_CASES: tuple[str, ...] = (
    "a.txt",
    "dir/sub/file.bin",
    "with space.txt",
    ".hidden/file",
    # Deliberately laxer than the remote-path validation: a file the engine can
    # legitimately have synced must stay restorable.
    "aux.txt",
    "",
    "/etc/passwd",
    "\\windows\\system32",
    "C:/Windows",
    "../outside",
    "a/../../b",
    "a//b",
    "a/",
    "./a",
    "bad\x00name",
    "back\\slash",
)


def _without(record: dict[str, object], *keys: str) -> dict[str, object]:
    """Copy of *record* without *keys* (an entry as an older writer left it)."""
    return {key: value for key, value in record.items() if key not in keys}


def _entry_case(why: str, record: dict[str, object]) -> dict[str, object]:
    """One ``entry.json`` case: the input, and the verdict the live rules give."""
    return {"why": why, "payload": record, "accepted": parse_trash_entry(record) is not None}


def _swept(
    why: str,
    entries: list[tuple[str, int, int]],
    *,
    retention_days: int,
    budget: int,
    now: int,
    broken: list[tuple[str, str]] | None = None,
) -> dict[str, object]:
    """One sweep case: ``(entry id, deleted_at, size)`` triples and their plan.

    The verdicts come from [plan_trash_sweep], never from a hand-written number,
    so a rule change regenerates them and a front-end still applying the old rule
    fails its parity test.

    *broken* lists the entry directories a real store can hold that no sweep may
    keep — ``(entry id, kind)`` with a kind each side can reproduce
    (``no-record``, ``payload-missing``, ``payload-mismatch``). They are not part
    of the plan (the walk removes them before it), so only their count is
    published.
    """
    plan = plan_trash_sweep(
        [
            TrashSweepEntry(entry_id=entry_id, deleted_at=when, size=size)
            for entry_id, when, size in entries
        ],
        retention_days=retention_days,
        budget=budget,
        now=now,
    )
    unusable = broken or []
    for entry_id, kind in unusable:
        if kind not in _BROKEN_KINDS:
            raise ValueError(f"unknown broken entry kind for {entry_id!r}: {kind!r}")
    return {
        "why": why,
        "now": now,
        "retention_days": retention_days,
        "budget": budget,
        "entries": [
            {"entry_id": entry_id, "deleted_at": when, "size": size}
            for entry_id, when, size in entries
        ],
        "broken": [{"entry_id": entry_id, "kind": kind} for entry_id, kind in unusable],
        "expired": sorted(plan.expired),
        "evicted": sorted(plan.evicted),
        "kept": plan.kept,
        "freed": plan.freed,
        "discarded": len(unusable),
    }


# The ways a stored entry can be unusable while still on disk. Each front-end
# reproduces them in its sweep test; an unknown kind must fail, never be guessed.
_BROKEN_KINDS: tuple[str, ...] = ("no-record", "payload-missing", "payload-mismatch")

# The sweep cases share one instant (and a budget large enough to never evict)
# so a retention case only exercises the window, and vice versa.
_SWEEP_NOW = 1_700_000_000
_SWEEP_BUDGET = 1_000_000
_SWEEP_OLD = _SWEEP_NOW - 40 * _SECONDS_PER_DAY  # outside a 30-day window
_SWEEP_CUTOFF = _SWEEP_NOW - 30 * _SECONDS_PER_DAY  # exactly at it
_SWEEP_YOUNG = _SWEEP_NOW - 10 * _SECONDS_PER_DAY  # inside it
_SWEEP_SAME_SECOND = _SWEEP_NOW - 1_000_000


def _sweep_cases() -> list[dict[str, object]]:
    """The ``prune_cases`` of the contract: retention, eviction and their order."""
    return [
        _swept(
            "the window expires what is older than it",
            [
                (f"{_SWEEP_OLD}-aaaaaaaaaaaa", _SWEEP_OLD, 10),
                (f"{_SWEEP_CUTOFF}-bbbbbbbbbbbb", _SWEEP_CUTOFF, 20),
                (f"{_SWEEP_YOUNG}-cccccccccccc", _SWEEP_YOUNG, 30),
            ],
            retention_days=30,
            budget=_SWEEP_BUDGET,
            now=_SWEEP_NOW,
            broken=[
                (f"{_SWEEP_YOUNG}-dddddddddddd", "no-record"),
                (f"{_SWEEP_YOUNG}-eeeeeeeeeeee", "payload-missing"),
                (f"{_SWEEP_YOUNG}-ffffffffffff", "payload-mismatch"),
            ],
        ),
        _swept(
            "a zero window keeps everything",
            [
                (f"{_SWEEP_OLD}-aaaaaaaaaaaa", _SWEEP_OLD, 10),
                (f"{_SWEEP_YOUNG}-bbbbbbbbbbbb", _SWEEP_YOUNG, 20),
            ],
            retention_days=0,
            budget=_SWEEP_BUDGET,
            now=_SWEEP_NOW,
        ),
        _swept(
            "the budget evicts the oldest entry first",
            [
                (f"{_SWEEP_YOUNG}-bbbbbbbbbbbb", _SWEEP_YOUNG, 60),
                (f"{_SWEEP_OLD}-aaaaaaaaaaaa", _SWEEP_OLD, 60),
            ],
            retention_days=0,
            budget=100,
            now=_SWEEP_NOW,
        ),
        _swept(
            "entries of the same second fall back to the entry id",
            [
                (f"{_SWEEP_SAME_SECOND}-bbbbbbbbbbbb", _SWEEP_SAME_SECOND, 60),
                (f"{_SWEEP_SAME_SECOND}-aaaaaaaaaaaa", _SWEEP_SAME_SECOND, 60),
            ],
            retention_days=0,
            budget=100,
            now=_SWEEP_NOW,
        ),
        _swept(
            "a total at the budget is kept",
            [(f"{_SWEEP_YOUNG}-aaaaaaaaaaaa", _SWEEP_YOUNG, 100)],
            retention_days=0,
            budget=100,
            now=_SWEEP_NOW,
        ),
        _swept(
            "the window runs before the budget",
            [
                (f"{_SWEEP_OLD}-aaaaaaaaaaaa", _SWEEP_OLD, 80),
                (f"{_SWEEP_YOUNG}-aaaaaaaaaaaa", _SWEEP_YOUNG, 60),
                (f"{_SWEEP_YOUNG}-bbbbbbbbbbbb", _SWEEP_YOUNG, 50),
            ],
            retention_days=30,
            budget=100,
            now=_SWEEP_NOW,
        ),
    ]


def build_trash_contract() -> dict[str, Any]:
    """Build the cross-language trash contract (fixture ``trash-contract``).

    Every value a front-end reproduces: the layout names, the id patterns, the
    defaults and policy bounds, the restore vocabulary, and one verdict per case
    of the two rules that decide whether a record is usable ([is_safe_relpath],
    [parse_trash_entry]). The inputs are hand-written, the verdicts are computed
    here, so regenerating the fixture is what turns a rule change into a failing
    parity test everywhere the old rule is still assumed.

    Consumers: ``hsync-client`` (store and CLI, through the shared constants),
    ``hsync-android`` (``TrashContractParityTest``), the ``hsync-desktop`` and
    ``hsync-wd-os5`` mirrors, and the fixture drift tests.
    """
    entry_cases = [
        _entry_case("a complete record", dict(_CONTRACT_RECORD)),
        _entry_case("the user origin", {**_CONTRACT_RECORD, "origin": TRASH_ORIGIN_USER}),
        _entry_case(
            "a record without optional metadata",
            _without(_CONTRACT_RECORD, "mtime_ns", "mode", "cid", "bucket", "origin"),
        ),
        _entry_case("an unsafe relpath", {**_CONTRACT_RECORD, "relpath": "../escape"}),
        _entry_case("an absolute relpath", {**_CONTRACT_RECORD, "relpath": "/etc/passwd"}),
        _entry_case("a backslash relpath", {**_CONTRACT_RECORD, "relpath": "back\\slash"}),
        _entry_case("an uppercase digest", {**_CONTRACT_RECORD, "sha256": "A" * 64}),
        _entry_case("a truncated digest", {**_CONTRACT_RECORD, "sha256": "abc"}),
        _entry_case("a missing digest", _without(_CONTRACT_RECORD, "sha256")),
        _entry_case("a missing size", _without(_CONTRACT_RECORD, "size")),
        _entry_case("a negative size", {**_CONTRACT_RECORD, "size": -1}),
        _entry_case("a zero deletion time", {**_CONTRACT_RECORD, "deleted_at": 0}),
        _entry_case("an unknown origin", {**_CONTRACT_RECORD, "origin": "somewhere-else"}),
        _entry_case("an empty origin", {**_CONTRACT_RECORD, "origin": ""}),
    ]
    return {
        "entry": {
            "filename": TRASH_ENTRY_FILENAME,
            "root_dirname": TRASH_DIRNAME,
            "payload_dirname": TRASH_PAYLOAD_DIRNAME,
            "restoring_suffix": TRASH_RESTORING_SUFFIX,
            "keys": sorted(TrashEntry.__annotations__),
        },
        "origins": list(TRASH_ORIGINS),
        "broken_kinds": list(_BROKEN_KINDS),
        "folder_id_pattern": _FOLDER_ID_RE.pattern,
        "entry_id_pattern": _ENTRY_ID_RE.pattern,
        "retention": {
            "days_default": TRASH_RETENTION_DAYS_DEFAULT,
            "days_max": TRASH_RETENTION_DAYS_MAX,
        },
        "budget": {
            "quota_percent": TRASH_QUOTA_PERCENT_DEFAULT,
            "quota_floor_mb": TRASH_QUOTA_FLOOR_MB_DEFAULT,
            "max_size_mb_default": TRASH_MAX_SIZE_MB_DEFAULT,
        },
        "tree": {"max_files": TREE_TRASH_MAX_FILES, "max_bytes": TREE_TRASH_MAX_BYTES},
        "sweep_interval_seconds": TRASH_SWEEP_INTERVAL_SECONDS,
        "restore_statuses": sorted(TRASH_RESTORE_STATUSES),
        "unrecoverable_restore": sorted(TRASH_UNRECOVERABLE_RESTORE),
        "restore_all_statuses": sorted(TRASH_RESTORE_ALL_STATUSES),
        "relpath_cases": [{"path": path, "safe": is_safe_relpath(path)} for path in _RELPATH_CASES],
        "entry_cases": entry_cases,
        "prune_cases": _sweep_cases(),
    }
