# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Durable, owner-only filesystem writes shared across HSYNC projects.

Every HSYNC component that persists a small state file (service identity, trust
store, ready file, stats) must guarantee the same two properties: a reader never
observes a partially written file, and the file is owner-only. This module owns
the write-through-temp + ``fsync`` + atomic-``replace`` recipe once, so a change
to the durability policy cannot silently leave one component behind.

The temp file lives in the destination directory (so ``os.replace`` is atomic on
the same filesystem) and is removed on every failure path.

Consumers: ``hsync-client`` (ready file, persistent device identity, trust
stores), ``hsync-rendezvous`` (node identity, stats file).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = [
    "DEFAULT_FILE_MODE",
    "atomic_write_bytes",
    "atomic_write_text",
]

DEFAULT_FILE_MODE = 0o600


def _fsync_dir(directory: str) -> None:
    """Best-effort fsync of *directory* so a rename survives a crash."""
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def atomic_write_bytes(
    path: str | Path,
    payload: bytes,
    *,
    mode: int = DEFAULT_FILE_MODE,
    fsync_dir: bool = False,
    unique_temp: bool = True,
    nofollow: bool = False,
) -> None:
    """Write *payload* to *path* atomically, owner-only by default.

    Args:
        path: Destination file.
        payload: Bytes to persist.
        mode: Permission bits for the destination (default ``0o600``).
        fsync_dir: Also fsync the parent directory after the rename, so the
            rename itself survives a crash (slower; used by durable stores).
        unique_temp: Use ``tempfile.mkstemp`` (default) so concurrent writers
            never share a temp path; when ``False`` a fixed ``.<name>.tmp`` is
            used with ``O_CREAT|O_TRUNC`` (plus ``O_NOFOLLOW`` when *nofollow*).
        nofollow: Add ``O_NOFOLLOW`` to the fixed-temp ``os.open`` (ignored when
            *unique_temp* is set).
    """
    target = Path(path)
    parent = target.parent
    if str(parent):
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    if unique_temp:
        fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(parent))
        os.chmod(tmp, mode)
    else:
        tmp = str(target.with_name(f".{target.name}.tmp"))
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if nofollow:
            flags |= os.O_NOFOLLOW
        fd = os.open(tmp, flags, mode)

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        if fsync_dir:
            _fsync_dir(str(parent))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    mode: int = DEFAULT_FILE_MODE,
    fsync_dir: bool = False,
    unique_temp: bool = True,
    nofollow: bool = False,
) -> None:
    """UTF-8 text sibling of :func:`atomic_write_bytes`."""
    atomic_write_bytes(
        path,
        text.encode("utf-8"),
        mode=mode,
        fsync_dir=fsync_dir,
        unique_temp=unique_temp,
        nofollow=nofollow,
    )
