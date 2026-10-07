# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Folder-ID marker and installation state-dir helpers.

A synced bucket is identified by a UUIDv4 written to ``.hsyncfolder`` at the
bucket root. Causal versions and tombstones live in an installation-level
SQLite database *outside* the bucket, keyed by that UUID (ADR-0025). The
marker travels with the folder so a rename/move re-anchors the same state.

Consumers: ``hsync-client`` (``sync_state`` / ``tombstones`` wrappers),
``hsync-server`` (state-dir resolution; server buckets use the ``buckets``
table instead of a marker), ``hsync-android`` (conceptual mirror in
``FolderMarker.kt`` / ``SyncStateManager``).
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from hsync_common.constants import (
    AUTH_DB_FILENAME,
    HSYNC_STATE_DB_ENV,
    HSYNC_STATE_DIR_ENV,
    HSYNCFOLDER_FILENAME,
    PARTIAL_DOWNLOAD_SUFFIX,
    SERVER_STATE_SUBDIR,
    STATE_INDEX_DB_FILENAME,
    SYNCSTATE_DIRNAME,
)

__all__ = [
    "client_state_db_dir",
    "client_state_db_path",
    "client_state_index_db_path",
    "default_state_dir",
    "ensure_folder_marker",
    "is_folder_id",
    "read_folder_marker",
    "server_auth_db_path",
    "server_state_db_path",
    "state_db_override",
    "write_folder_marker",
]

# UUIDv4 text form (36 chars) as written by :func:`uuid.uuid4`.
_FOLDER_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_folder_id(value: object) -> bool:
    """Return True when *value* is a UUIDv4 text string.

    Consumers: ``hsync-common`` (marker parse), ``hsync-client`` /
    ``hsync-server`` (reject a corrupt marker rather than treating it as a
    new folder silently when a well-formed id is required).
    """
    return isinstance(value, str) and _FOLDER_ID_RE.fullmatch(value) is not None


def default_state_dir() -> Path:
    """Return the installation state directory (not inside any bucket).

    Resolution order: ``HSYNC_STATE_DIR``, then ``$XDG_STATE_HOME/hsync``,
    then ``~/.local/state/hsync``. Consumers: ``hsync-client`` and
    ``hsync-server``; tests override via the env var.
    """
    override = os.environ.get(HSYNC_STATE_DIR_ENV)
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(Path.home(), ".local", "state")
    return Path(base) / "hsync"


def state_db_override() -> Path | None:
    """Return the explicit ``HSYNC_STATE_DB`` path, or ``None``.

    When set, both the client and the server open this single DB instead of the
    per-folder / per-bucket layout. Consumers: ``hsync-client``
    (``state_backend.resolve_bucket_folder``), ``hsync-server`` (``config``),
    tests.
    """
    value = os.environ.get(HSYNC_STATE_DB_ENV)
    return Path(value) if value else None


def client_state_db_dir(device_dir: Path) -> Path:
    """Return the per-device sync-state subdir ``<device_dir>/syncstate``.

    The ``device_dir`` (``$HSYNC_DEVICE_DIR`` or the OS default) is resolved by
    the caller (``hsync_client.identity.default_device_dir``) and passed in, so
    this module stays free of identity/env logic. Consumers: ``hsync-client``
    (``state_backend``), tests.
    """
    return device_dir / SYNCSTATE_DIRNAME


def client_state_db_path(folder_uuid: str, device_dir: Path) -> Path:
    """Return the per-folder DB path ``<device_dir>/syncstate/<uuid>.db``.

    Named by the ``.hsyncfolder`` UUID so a move/copy of the folder re-opens the
    same state. Consumers: ``hsync-client`` (``state_backend``), tests.
    """
    return client_state_db_dir(device_dir) / f"{folder_uuid}.db"


def client_state_index_db_path(device_dir: Path) -> Path:
    """Return the per-device ``canonical_path -> folder uuid`` index DB.

    Consulted only when a folder's ``.hsyncfolder`` is missing (re-anchoring).
    Consumers: ``hsync-client`` (``state_backend``), tests.
    """
    return client_state_db_dir(device_dir) / STATE_INDEX_DB_FILENAME


def server_state_db_path(bucket: str, state_dir: Path) -> Path:
    """Return the per-bucket server DB ``<state_dir>/server/<bucket>.db``.

    The filename is the bucket name itself, which is validated
    (``^[A-Za-z0-9]([A-Za-z0-9_-]*[A-Za-z0-9])?$``) so no separators, leading
    dot or ``..`` are possible. ``state_dir`` is resolved by the caller
    (``hsync_server.config.get_state_dir``). Consumers: ``hsync-server``
    (``config``), tests.
    """
    return state_dir / SERVER_STATE_SUBDIR / f"{bucket}.db"


def server_auth_db_path(state_dir: Path) -> Path:
    """Return the global server auth DB ``<state_dir>/server/auth.db``.

    Auth (API keys) is installation-global, not per bucket, so it never uses the
    per-bucket file. ``state_dir`` is resolved by the caller. Consumers:
    ``hsync-server`` (``auth_store``), tests.
    """
    return state_dir / SERVER_STATE_SUBDIR / AUTH_DB_FILENAME


def read_folder_marker(bucket_dir: str | Path) -> str | None:
    """Read the folder UUID from ``.hsyncfolder``, or ``None`` if absent/invalid.

    A missing, unreadable or structurally invalid marker is treated as
    "no marker" so the caller can generate a fresh UUID. Consumers:
    ``hsync-client`` (open existing bucket), ``hsync-android`` (SAF/path
    mirror).
    """
    path = Path(bucket_dir) / HSYNCFOLDER_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    value = raw.strip()
    return value if is_folder_id(value) else None


def write_folder_marker(bucket_dir: str | Path, folder_id: str) -> str:
    """Atomically write *folder_id* to ``.hsyncfolder`` (tmp + rename).

    *folder_id* must already be a valid UUIDv4. Consumers: ``hsync-client``
    (first run / copy-as-new-folder), tests.
    """
    if not is_folder_id(folder_id):
        raise ValueError(f"invalid folder id: {folder_id!r}")
    bucket = Path(bucket_dir)
    bucket.mkdir(parents=True, exist_ok=True)
    dest = bucket / HSYNCFOLDER_FILENAME
    tmp = dest.with_name(f"{HSYNCFOLDER_FILENAME}{PARTIAL_DOWNLOAD_SUFFIX}")
    tmp.write_text(f"{folder_id}\n", encoding="utf-8")
    tmp.replace(dest)
    return folder_id


def ensure_folder_marker(bucket_dir: str | Path) -> str:
    """Return the folder UUID, generating and writing a marker if needed.

    Consumers: ``hsync-client`` (``sync_state`` / ``tombstones`` on first
    access of a bucket).
    """
    existing = read_folder_marker(bucket_dir)
    if existing is not None:
        return existing
    return write_folder_marker(bucket_dir, str(uuid.uuid4()))
