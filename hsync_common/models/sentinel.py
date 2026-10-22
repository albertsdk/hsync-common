# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""``.hsynckeep`` sentinels and the empty-directory lifecycle.

A directory with no syncable entry carries no content to list, so an engine
would drop it from the snapshot. The structure is preserved by an empty marker
file named :data:`hsync_common.constants.HSYNCKEEP_FILENAME`; the reverse
operation removes a directory once it holds no entry at all.

Both rules are transport-independent and must stay identical on every receiver
(otherwise a delete on the server and the same delete on the P2P master leave
different trees), so they live here instead of in each project.

Consumers: ``hsync-server`` (``api/file_utils.py``), ``hsync-client``
(``sync.ensure_sentinel``, ``utils.paths.safe_rmdir_if_empty``), tests.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger as log

from hsync_common.constants import HSYNCKEEP_FILENAME
from hsync_common.models.file import is_hidden_file

__all__ = ["ensure_sentinel", "is_sentinel_file", "remove_empty_dir"]


def _same_path(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    """Case- and separator-insensitive absolute comparison of two paths."""
    return os.path.normcase(os.path.abspath(os.fspath(a))) == os.path.normcase(
        os.path.abspath(os.fspath(b))
    )


def is_sentinel_file(filepath: str | os.PathLike[str]) -> bool:
    """True when *filepath* names a ``.hsynckeep`` sentinel."""
    return Path(filepath).name == HSYNCKEEP_FILENAME


def ensure_sentinel(dir_path: str | os.PathLike[str]) -> bool:
    """Create a ``.hsynckeep`` sentinel when *dir_path* has no syncable entry.

    A directory counts as empty when every entry is hidden (the marker itself is
    hidden, so an existing one prevents a second creation). Returns True only
    when this call created the file; a missing/unreadable directory is a no-op.
    """
    try:
        entries = os.listdir(dir_path)
    except OSError:
        return False
    if any(not is_hidden_file(entry) for entry in entries):
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
