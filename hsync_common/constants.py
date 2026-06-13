# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Shared constants for HSYNC.

This module defines constants that are common to both hsync-client
and hsync-server, ensuring consistency across the entire system.
"""

# =============================================================================
# Application Version
# =============================================================================

# Single source of truth for the HSYNC protocol version.
# Both client and server must use the same version for compatibility.
VERSION = "1.0.0"

# =============================================================================
# Sentinel File for Empty Directories
# =============================================================================

# Sentinel filename placed in empty directories to force sync of the
# directory structure.  Similar to Git's .gitkeep convention.
# This file is treated as *not* hidden by is_hidden_file() so it passes
# through the sync engine, but it is filtered from the desktop UI.
HSYNCKEEP_FILENAME = ".hsynckeep"

# Per-bucket ignore file with gitignore-style patterns.  When present at
# the bucket root it is parsed by hsync_common.ignore.IgnoreMatcher and
# its rules are layered on top of (or replace, depending on sync_hidden)
# the default hidden-file detection.
HSYNCIGNORE_FILENAME = ".hsyncignore"

# Per-bucket deletion-marker (tombstone) side-car file.  Maps a hashed
# bucket-relative path to the deletion timestamp and the content hash of the
# removed file, so that a peer that was offline at deletion time does not
# resurrect the file during a full reconciliation.  Starts with a dot, so it
# is treated as hidden and never exchanged across peers.
HSYNCTOMBSTONES_FILENAME = ".hsynctombstones"

# Per-peer sync-state (version) side-car file.  Maps a hashed bucket-relative
# path to the last-synced common ancestor (base_hash) plus version lineage
# (change_id, origin_cid), enabling a clock-independent three-way merge: a peer
# can tell whether only the local side, only the remote side, or both sides
# changed since the last successful sync.  Local and private to each peer (never
# exchanged); starts with a dot, so it is treated as hidden.
HSYNCSTATE_FILENAME = ".hsyncstate"

# =============================================================================
# File Transfer Settings
# =============================================================================

# Chunk sizes based on file size for optimal checksum computation
CHUNK_SIZE_SMALL = 8 * 1024  # 8KB for files < 1MB
CHUNK_SIZE_MEDIUM = 64 * 1024  # 64KB for files < 100MB
CHUNK_SIZE_LARGE = 256 * 1024  # 256KB for files >= 100MB

# File size thresholds for chunk size selection
FILE_SIZE_SMALL = 1_000_000  # 1MB
FILE_SIZE_MEDIUM = 100_000_000  # 100MB

# =============================================================================
# Partial Transfer Artifacts
# =============================================================================

# Suffix appended to in-progress transfer targets. Bytes are streamed to
# "<final>.part" and atomically renamed to the final name only after the
# SHA-256 checksum is verified, so a "<name>.part" file is always a transient
# internal artifact that must never be synced, listed, or treated as user data.
PARTIAL_DOWNLOAD_SUFFIX = ".part"
