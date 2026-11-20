# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""``.hsynckeep`` sentinels and the empty-directory lifecycle.

A directory with no syncable entry carries no content to list, so an engine
would drop it from the snapshot. The structure is preserved by an empty marker
file named :data:`hsync_common.constants.HSYNCKEEP_FILENAME`; the reverse
operation removes a directory once it holds no entry at all, and a marker left
behind in a directory that later received content is dropped again — a stale
marker is what makes a status pass read a populated directory as an empty one.

All three rules are transport-independent and must stay identical on every
receiver (otherwise a delete on the server and the same delete on the P2P master
leave different trees), so they live here instead of in each project.

Consumers: ``hsync-server`` (``api/file_utils.py``), ``hsync-client``
(``sync.ensure_sentinel`` / ``sync.prune_sentinel`` and their
``sync.ensure_hsynckeep_files`` walk, the P2P watchers),
``utils.paths.safe_rmdir_if_empty``, tests.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from loguru import logger as log

from hsync_common.constants import HSYNCKEEP_FILENAME
from hsync_common.models.file import is_hidden_file

__all__ = [
    "dir_has_syncable_entry",
    "ensure_sentinel",
    "is_sentinel_file",
    "prune_sentinel",
    "remove_empty_dir",
]


def _same_path(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    """Case- and separator-insensitive absolute comparison of two paths."""
    return os.path.normcase(os.path.abspath(os.fspath(a))) == os.path.normcase(
        os.path.abspath(os.fspath(b))
    )


def is_sentinel_file(filepath: str | os.PathLike[str]) -> bool:
    """True when *filepath* names a ``.hsynckeep`` sentinel."""
    return Path(filepath).name == HSYNCKEEP_FILENAME


def _has_syncable_entry(entries: Iterable[str]) -> bool:
    """True when *entries* holds something the engine synchronises.

    The marker itself is never content: a lone ``.hsynckeep`` is exactly what an
    empty directory looks like.
    """
    return any(name != HSYNCKEEP_FILENAME and not is_hidden_file(name) for name in entries)


def dir_has_syncable_entry(dir_path: str | os.PathLike[str]) -> bool | None:
    """Whether *dir_path* holds an entry the engine synchronises.

    The exact emptiness rule :func:`ensure_sentinel` applies, exposed for
    callers that must only *read* it (``hsync-client``'s empty-directory
    verdict, which runs on a listing and must not create a marker). A
    subdirectory is content, exactly as it is for the marker's own rule.
    ``None`` when the directory cannot be read.
    """
    try:
        entries = os.listdir(dir_path)
    except OSError:
        return None
    return _has_syncable_entry(entries)


def ensure_sentinel(dir_path: str | os.PathLike[str]) -> bool:
    """Create a ``.hsynckeep`` sentinel when *dir_path* has no syncable entry.

    A directory counts as empty when every entry is hidden. Returns True only
    when this call created the file; a missing/unreadable directory is a no-op.
    """
    has_content = dir_has_syncable_entry(dir_path)
    if has_content is None or has_content:
        return False
    sentinel = Path(dir_path) / HSYNCKEEP_FILENAME
    if sentinel.exists():
        return False
    try:
        sentinel.touch()
    except OSError as exc:
        log.warning(f'Cannot create sentinel "{sentinel}": {exc}')
        return False
    return True


def prune_sentinel(dir_path: str | os.PathLike[str]) -> bool:
    """Drop the ``.hsynckeep`` marker of *dir_path* once it holds content.

    A directory that is momentarily empty while a copy runs gets a marker; the
    first real entry makes it stale, and a stale marker is indistinguishable
    from an empty directory for every reader of the marker. Returns True only
    when this call removed one; a directory without a marker, with only hidden
    entries, or unreadable is a no-op.
    """
    sentinel = Path(dir_path) / HSYNCKEEP_FILENAME
    if not sentinel.exists():
        return False
    if not dir_has_syncable_entry(dir_path):
        return False
    try:
        sentinel.unlink()
    except OSError as exc:
        log.warning(f'Cannot remove stale sentinel "{sentinel}": {exc}')
        return False
    return True


def remove_empty_dir(
    dir_path: str | os.PathLike[str] | None,
    *,
    keep_root: str | os.PathLike[str] | None = None,
) -> bool:
    """Remove *dir_path* when it holds no entry at all; report whether it went.

    ``keep_root`` (typically the bucket root) is never removed, even when empty:
    a peer deleting the root sentinel must not destroy the sync target.
    """
    if not dir_path:
        return False
    path = Path(dir_path)
    if keep_root is not None and _same_path(path, keep_root):
        return False
    try:
        path.rmdir()  # raises when non-empty: exactly the guard needed
    except OSError:
        return False
    return True
