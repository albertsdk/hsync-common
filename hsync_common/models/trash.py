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
from pathlib import Path
from typing import TypedDict, cast

from hsync_common.constants import (
    TRASH_DIR_ENV,
    TRASH_DIRNAME,
    TRASH_ENTRY_FILENAME,
    TRASH_PAYLOAD_DIRNAME,
)
from hsync_common.hashing import is_lower_sha256_hex
from hsync_common.state_paths import state_path

__all__ = [
    "TRASH_ENTRY_FILENAME",
    "TRASH_ORIGINS",
    "TRASH_ORIGIN_SYNC",
    "TRASH_ORIGIN_USER",
    "TRASH_PAYLOAD_DIRNAME",
    "TrashEntry",
    "entry_dir",
    "entry_payload_path",
    "is_safe_entry_id",
    "is_safe_folder_id",
    "is_safe_relpath",
    "parse_trash_entry",
    "trash_folder_dir",
    "trash_root",
]

# Why the file was trashed: the sync engine applied a deletion, or the user
# removed it through a front-end. Both end up in the same store so one restore
# path covers them.
TRASH_ORIGIN_SYNC = "sync"
TRASH_ORIGIN_USER = "user"
TRASH_ORIGINS = (TRASH_ORIGIN_SYNC, TRASH_ORIGIN_USER)

# ``<unix seconds>-<random hex>``: sorts by age as a string, which the retention
# sweep relies on.
_ENTRY_ID_RE = re.compile(r"^[0-9]{10,}-[0-9a-f]{8,32}$")
# ``.hsyncfolder`` holds a UUIDv4; the store also accepts any bounded token so a
# hand-created marker cannot escape the root.
_FOLDER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


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
    origin = _as_str(data, "origin") or TRASH_ORIGIN_SYNC
    if not is_safe_relpath(relpath) or not is_lower_sha256_hex(sha256):
        return None
    if origin not in TRASH_ORIGINS:
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
