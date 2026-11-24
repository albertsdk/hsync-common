# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Server history: the record of one replaced or deleted blob (ADR-0057).

The server keeps a single blob per path, so an overwrite destroys the previous
content and a delete destroys the last one. This store keeps those bytes for a
retention window, per bucket, under the installation state dir — outside every
served bucket, so no peer sees it and the wire protocol is unchanged.

Layout, under the history root::

    <bucket>/<entry id>/entry.json          this record
    <bucket>/<entry id>/payload/<relpath>   the bytes, at their bucket path

The shape is the sync trash's (ADR-0056) on purpose — one payload convention,
one set of path-safety helpers — while the **entity** stays distinct: an
overwrite is not a deletion, so ``reason`` replaces the trash's ``origin`` and
``recorded_at`` replaces ``deleted_at``. Both front-ends read it through the
server's ``admin history list --json``; nobody re-derives the layout.

Consumers: ``hsync-server`` (store, admin CLI), shared fixtures/tests.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict, cast

from hsync_common.constants import (
    HISTORY_DIRNAME,
    HISTORY_ENTRY_FILENAME,
    HISTORY_PAYLOAD_DIRNAME,
    HISTORY_REASON_DELETE,
    HISTORY_REASON_OVERWRITE,
    HISTORY_REASONS,
)
from hsync_common.hashing import is_lower_sha256_hex
from hsync_common.models.trash import is_safe_entry_id, is_safe_folder_id, is_safe_relpath
from hsync_common.state_paths import state_path

__all__ = [
    "HISTORY_ENTRY_FILENAME",
    "HISTORY_PAYLOAD_DIRNAME",
    "HISTORY_REASONS",
    "HISTORY_REASON_DELETE",
    "HISTORY_REASON_OVERWRITE",
    "HistoryEntry",
    "history_bucket_dir",
    "history_entry_dir",
    "history_entry_payload_path",
    "history_root",
    "parse_history_entry",
]


class HistoryEntry(TypedDict):
    """Serialized record of one replaced or deleted blob (``entry.json``).

    Consumers: ``hsync-server`` (store, ``admin history list --json``), tests.
    """

    relpath: str  # bucket-relative path, POSIX separators
    sha256: str  # content hash of the preserved bytes
    size: int  # bytes
    mtime_ns: int  # mtime the blob had when it was replaced or removed
    mode: int  # permission bits; 0 where the platform does not represent them
    recorded_at: int  # unix seconds
    reason: str  # one of HISTORY_REASONS
    cid: str | None  # client whose write or deletion caused the entry
    bucket: str  # bucket the blob belonged to


def history_root(directory: str | Path | None = None) -> Path:
    """Return the history root: *directory*, else ``<state dir>/history``.

    Consumers: ``hsync-server`` (store, admin CLI), tests.
    """
    if directory is not None and str(directory).strip():
        return Path(directory).expanduser()
    return state_path(HISTORY_DIRNAME)


def history_bucket_dir(root: Path, bucket: str) -> Path:
    """Return one bucket's history directory, refusing an unsafe bucket name."""
    if not is_safe_folder_id(bucket):
        raise ValueError(f"unsafe bucket name for the history store: {bucket!r}")
    return root / bucket


def history_entry_dir(root: Path, bucket: str, entry_id: str) -> Path:
    """Return one entry's directory, refusing an unsafe entry id.

    The id has the trash's shape (``<unix seconds>-<random hex>``, validated by
    ``is_safe_entry_id``) so both stores sort by age as a plain string.
    """
    if not is_safe_entry_id(entry_id):
        raise ValueError(f"unsafe history entry id: {entry_id!r}")
    return history_bucket_dir(root, bucket) / entry_id


def history_entry_payload_path(entry: Path | str, relpath: str) -> Path:
    """Return the payload path of *relpath* inside *entry*, verified contained.

    Raises:
        ValueError: the relpath is unsafe or resolves outside the entry.
    """
    if not is_safe_relpath(relpath):
        raise ValueError(f"unsafe history relpath: {relpath!r}")
    base = Path(entry) / HISTORY_PAYLOAD_DIRNAME
    candidate = base / relpath
    normalised = Path(os.path.normpath(str(candidate)))
    if normalised != candidate:
        raise ValueError(f"unsafe history relpath: {relpath!r}")
    return candidate


def _as_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _as_int(payload: dict[str, object], key: str, *, minimum: int = 0) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def parse_history_entry(payload: object) -> HistoryEntry | None:
    """Validate an ``entry.json`` payload read from disk.

    A damaged or hand-edited record is skipped rather than trusted: every field a
    restore needs (path, hash, size) must be structurally valid, the relpath must
    be safe and the reason must be one this store mints. Returns ``None`` when the
    payload is unusable.

    Consumers: ``hsync-server`` (listing and restore), tests.
    """
    if not isinstance(payload, dict):
        return None
    data = cast(dict[str, object], payload)
    relpath = _as_str(data, "relpath")
    sha256 = _as_str(data, "sha256")
    reason = _as_str(data, "reason")
    if not is_safe_relpath(relpath) or not is_lower_sha256_hex(sha256):
        return None
    if reason not in HISTORY_REASONS:
        return None
    size = _as_int(data, "size")
    recorded_at = _as_int(data, "recorded_at", minimum=1)
    if size is None or recorded_at is None:
        return None
    mtime_ns = _as_int(data, "mtime_ns")
    mode = _as_int(data, "mode")
    cid = data.get("cid")
    return HistoryEntry(
        relpath=relpath,
        sha256=sha256,
        size=size,
        mtime_ns=mtime_ns or 0,
        mode=mode or 0,
        recorded_at=recorded_at,
        reason=reason,
        cid=cid if isinstance(cid, str) and cid else None,
        bucket=_as_str(data, "bucket"),
    )
