# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Data models package for HSYNC Common.

This package contains the canonical data classes for file synchronization
operations, shared between hsync-client and hsync-server.
"""

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
from hsync_common.models.history import (
    HISTORY_REASON_DELETE,
    HISTORY_REASON_OVERWRITE,
    HISTORY_REASONS,
    HistoryEntry,
    parse_history_entry,
)
from hsync_common.models.symlink import Symlink
from hsync_common.models.sync_action import SyncAction, SyncActionName
from hsync_common.models.tombstone import (
    TombstoneEntry,
    TombstoneStore,
    relpath_in_bucket,
    tombstone_key,
)
from hsync_common.models.trash import (
    TRASH_ORIGIN_SYNC,
    TRASH_ORIGIN_USER,
    TRASH_ORIGINS,
    TrashEntry,
    entry_dir,
    entry_payload_path,
    is_safe_entry_id,
    is_safe_folder_id,
    is_safe_relpath,
    parse_trash_entry,
    trash_folder_dir,
    trash_root,
)

__all__ = [
    "HISTORY_REASONS",
    "HISTORY_REASON_DELETE",
    "HISTORY_REASON_OVERWRITE",
    "TRASH_ORIGINS",
    "TRASH_ORIGIN_SYNC",
    "TRASH_ORIGIN_USER",
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
    "HistoryEntry",
    "Symlink",
    "SyncAction",
    "SyncActionName",
    "TombstoneEntry",
    "TombstoneStore",
    "TrashEntry",
    "clear_sha256_cache",
    "entry_dir",
    "entry_payload_path",
    "invalidate_sha256_cache",
    "is_hidden_dir",
    "is_hidden_file",
    "is_safe_entry_id",
    "is_safe_folder_id",
    "is_safe_relpath",
    "parse_history_entry",
    "parse_trash_entry",
    "relpath_in_bucket",
    "tombstone_key",
    "trash_folder_dir",
    "trash_root",
]
