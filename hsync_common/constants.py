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
# its rules are layered on top of the default ignore patterns.
HSYNCIGNORE_FILENAME = ".hsyncignore"

# =============================================================================
# Default Ignore Patterns (OS cache / temporary files)
# =============================================================================

# Built-in gitignore-style patterns that are *always* active, regardless of
# user configuration.  Following industry standard (Syncthing, rsync,
# Nextcloud, OneDrive) these cover only operating-system cache files and
# editor/office temporary files — NOT dotfiles in general, which are
# synchronised normally.
#
# Users can re-include any of these via negation rules in ``.hsyncignore``
# (e.g. ``!*.tmp``) or override them with more specific patterns.
DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    # --- macOS Finder / Spotlight cache ---
    ".DS_Store",
    "._*",
    ".Spotlight-V100",
    ".Trashes",
    # --- Windows Explorer / thumbnail cache ---
    "Thumbs.db",
    "Thumbs.db:encryptable",
    "ehthumbs.db",
    "ehthumbs_vista.db",
    "desktop.ini",
    # --- Microsoft Office lock / temp files ---
    "~$*",
    # --- Editor swap / backup / lock files ---
    ".*.sw?",
    "*~",
    "4913",
    ".~lock.*#",
    # --- Editor / application safe-save temp files ---
    # GNOME GIO (gedit, nautilus, …) writes to ".goutputstream-XXXX" then
    # atomically renames over the final file. The temp must never be synced;
    # the watcher reframes the rename as a content modification of the dest.
    ".goutputstream-*",
    # --- Generic temporary / backup files ---
    "*.tmp",
    "*.temp",
    "*.bak",
    # --- Date-stamped backup files (e.g. file-2024-01-15-120000) ---
    "*-????-??-??-??????",
)

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

# Suffix appended to in-progress *delta* reconstruction targets. Distinct from
# PARTIAL_DOWNLOAD_SUFFIX so an interrupted delta transfer is recognisable (and
# cleaned up) separately from a plain interrupted download.
PARTIAL_DELTA_SUFFIX = ".delta.part"

# =============================================================================
# Delta Transfer (rsync-style) Settings
# =============================================================================

# Minimum file size for delta transfer to be worthwhile. Below this threshold
# the signature/matching overhead exceeds the bandwidth saved.
DELTA_MIN_FILE_SIZE = 256 * 1024  # 256 KB (remote/server mode)

# Higher threshold for LAN mode: on gigabit links with slow CPUs (e.g. NAS ARM)
# the signature computation cost can exceed the bandwidth saving, so delta is
# only attempted for larger files (same rationale as the LAN compression floor).
DELTA_MIN_FILE_SIZE_LAN = 1024 * 1024  # 1 MB

# Maximum fraction of changed base blocks for delta to stay worthwhile; above
# this the sender aborts and falls back to a full transfer.
DELTA_MAX_CHANGE_RATIO = 0.50  # 50%

# Hard cap on the literal payload produced by a single delta. Beyond this the
# delta degenerates into a full transfer anyway, so it is aborted up-front.
DELTA_MAX_LITERAL_SIZE = 1024 * 1024 * 1024  # 1 GB

# Time-to-live (seconds) of a server-issued literal-payload download token.
DELTA_TOKEN_TTL = 300  # 5 minutes

# Adaptive block sizes selected by base-file size (see delta.decision).
DELTA_BLOCK_SIZE_SMALL = 4 * 1024  # 4 KB  (< 1 MB)
DELTA_BLOCK_SIZE_MEDIUM = 16 * 1024  # 16 KB (1–10 MB)
DELTA_BLOCK_SIZE_LARGE = 64 * 1024  # 64 KB (10–100 MB)
DELTA_BLOCK_SIZE_XLARGE = 256 * 1024  # 256 KB (> 100 MB)

# Base-file size thresholds for block-size selection.
DELTA_FILE_SIZE_SMALL = 1 * 1024 * 1024  # 1 MB
DELTA_FILE_SIZE_MEDIUM = 10 * 1024 * 1024  # 10 MB
DELTA_FILE_SIZE_LARGE = 100 * 1024 * 1024  # 100 MB

# Wire DoS guards: maximum number of signatures in an exchange and operations
# in a delta-instructions payload (bounds JSON size and matching work).
DELTA_MAX_SIGNATURES = 100_000
DELTA_MAX_OPS = 100_000

# TOCTOU re-hash threshold: files smaller than this get a full SHA-256 re-hash
# after the rolling scan to detect content changes that mtime+size alone miss.
# 10 MB is a reasonable cutoff — re-hashing is fast enough to not impact UX.
DELTA_TOCTOU_REHASH_THRESHOLD = 10 * 1024 * 1024  # 10 MB
