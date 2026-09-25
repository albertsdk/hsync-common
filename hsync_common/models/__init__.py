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
    "Symlink",
    "SyncAction",
    "SyncActionName",
    "TombstoneEntry",
    "TombstoneStore",
    "clear_sha256_cache",
    "invalidate_sha256_cache",
    "is_hidden_dir",
    "is_hidden_file",
    "relpath_in_bucket",
    "tombstone_key",
]
