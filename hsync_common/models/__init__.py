# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Data models package for HSYNC Common.

This package contains the canonical data classes for file synchronization
operations, shared between hsync-client and hsync-server.
"""

from pathlib import Path


def _resolve_prefixed_path(data_filepath: str, prefix: str | None, *, strip: bool) -> str:
    """Resolve a filepath from a serialized dict with an optional prefix.

    Shared across :meth:`File.from_dict`, :meth:`Symlink.from_dict` and
    :meth:`Dir.from_dict` so the serialisation contract is defined once.

    Args:
        data_filepath: Raw ``filepath`` / ``path`` value from the dict.
        prefix: Base directory prefix (``dir_prefix`` / ``localpath``).
        strip: When ``True`` the prefix is stripped from *data_filepath*
            (making it bucket-relative, component-aware: a path outside
            *prefix* is kept verbatim); when ``False`` the prefix is
            prepended (making it absolute).

    Returns:
        The resolved path string.

    Raises:
        ValueError: When *strip* is ``True`` but *prefix* is falsy.
    """
    if strip and not prefix:
        raise ValueError("Set dir_prefix to strip it.")
    if strip and prefix:
        try:
            rel = str(Path(data_filepath).relative_to(prefix))
        except ValueError:
            # Not under prefix: keep the original path verbatim. Component-aware
            # stripping (matching Event.correct_path) never mangles a sibling
            # path that merely shares the string prefix (e.g. "/base2/x" vs
            # "/base" must not become "2/x").
            return str(data_filepath)
        return "" if rel == "." else rel.lstrip("/")
    if prefix:
        return str(Path(prefix) / str(data_filepath).lstrip("/"))
    return str(data_filepath)


from hsync_common.models.delta import (
    BlockSignature,
    BlockSignatureDict,
    DeltaInstructions,
    DeltaInstructionsDict,
    DeltaOp,
    DeltaOpDict,
)
from hsync_common.models.dir import Dir, is_hidden_dir
from hsync_common.models.event import Event, EventDict, EventName
from hsync_common.models.file import (
    File,
    FileDict,
    clear_sha256_cache,
    invalidate_sha256_cache,
    is_hidden_file,
)
from hsync_common.models.symlink import Symlink
from hsync_common.models.sync_action import SyncAction, SyncActionName
from hsync_common.models.tombstone import (
    TombstoneEntry,
    TombstoneStore,
    relpath_in_bucket,
    tombstone_key,
)

__all__ = [
    "BlockSignature",
    "BlockSignatureDict",
    "DeltaInstructions",
    "DeltaInstructionsDict",
    "DeltaOp",
    "DeltaOpDict",
    "Dir",
    "Event",
    "EventDict",
    "EventName",
    "File",
    "FileDict",
    "SyncAction",
    "SyncActionName",
    "Symlink",
    "TombstoneEntry",
    "TombstoneStore",
    "clear_sha256_cache",
    "invalidate_sha256_cache",
    "is_hidden_dir",
    "is_hidden_file",
    "relpath_in_bucket",
    "tombstone_key",
]
