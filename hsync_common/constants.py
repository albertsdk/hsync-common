# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Shared constants for HSYNC.

This module defines constants that are common to both hsync-client
and hsync-server, ensuring consistency across the entire system.
"""

import re
from typing import Final, Literal

# =============================================================================
# Application Version
# =============================================================================

# Single source of truth for the HSYNC application version, shared by client,
# server, desktop and Android. The wire-protocol versions live separately in
# hsync_common.protocol.handshake (PROTOCOL_VERSION_*).
HSYNC_VERSION = "1.0.8"

# =============================================================================
# HTTP Headers (wire protocol)
# =============================================================================

# Custom headers exchanged over REST. Single source of truth shared by
# hsync-client, hsync-server (re-exported in their local constants modules) and
# mirrored by hsync-android (Protocol.kt).
HEADER_CLIENT_NAME: Final[Literal["X-Client-Name"]] = "X-Client-Name"
HEADER_CLIENT_VERSION: Final[Literal["X-Client-Version"]] = "X-Client-Version"
HEADER_SERVER_VERSION: Final[Literal["X-Server-Version"]] = "X-Server-Version"
HEADER_PROTOCOL_VERSION: Final[Literal["X-Protocol-Version"]] = "X-Protocol-Version"
# Canonical response checksum header for full-file downloads. Consumers:
# hsync-client LAN master/seeder, hsync-server, and the Android Protocol mirror.
HEADER_CHECKSUM_SHA256: Final[Literal["X-Checksum-SHA256"]] = "X-Checksum-SHA256"

# Shape of a well-formed X-Client-Name value: a lowercase product slug
# ("hsync-client", "hsync-android"). It identifies the originating product,
# never an internal module or file, so values like "main_logic.py" or
# "HSYNC Client" are outside the contract from the start. The server applies
# the same pattern when it validates the header (see hsync-server middleware).
CLIENT_NAME_PATTERN = r"^[a-z][a-z0-9-]*[a-z0-9]$"

_CLIENT_NAME_RE = re.compile(CLIENT_NAME_PATTERN)

# Bare hostname / IPv4 charset for ``HOST[:PORT]`` endpoints. A host is
# alphanumeric, optionally dotted/hyphenated, but never starts or ends with
# ``-``/``.``. Anchors are left out so callers can embed it (bare ``^...$`` or
# inside a full URL pattern). IPv6 literals are bracketed separately by the
# consumers. Consumers: hsync_common.endpoint (the shared parser), hsync-client
# (CLI host parsing and the ``HSYNC_SERVER`` URL validator), hsync-bootnode and
# hsync-server (bind ``--host``).
HOSTNAME_PATTERN = r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?"


def is_valid_client_name(value: str) -> bool:
    """Return True when *value* is a well-formed client-name slug.

    Shared SSOT validator: the server middleware accepts/rejects the
    X-Client-Name header with this exact rule, so the client cannot drift.
    """
    return bool(_CLIENT_NAME_RE.fullmatch(value))


# =============================================================================
# HTTP Content Types (wire protocol)
# =============================================================================

# Media types shared across the ecosystem. Centralized here so the Python
# client/server and the Kotlin mirrors never diverge on the wire strings.
CONTENT_TYPE_OCTET_STREAM: Final[Literal["application/octet-stream"]] = "application/octet-stream"
CONTENT_TYPE_JSON: Final[Literal["application/json"]] = "application/json"

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
    # --- Browser download temp files ---
    # Chromium-based browsers (Chrome, Edge, Brave, …) write to
    # "filename.crdownload" during an active download and rename it to the
    # final name only when complete. The temp must never be synced (it would
    # propagate a truncated file); unlike a safe-save there is no rename to
    # reframe, so the temp is simply ignored until the browser removes it.
    "*.crdownload",
    # --- Generic temporary / backup files ---
    "*.tmp",
    "*.temp",
    "*.bak",
    # --- Date-stamped backup files (e.g. file-2024-01-15-120000) ---
    "*-????-??-??-??????",
)

# Folder-identity marker written at the bucket root (UUIDv4 text + newline).
# The marker travels with the folder so a rename/move re-anchors the external
# SQLite state; it is engine-owned and must never be accepted from the wire
# (ADR-0025). Consumers: hsync-client, hsync-server (docs only; server uses the
# buckets table), hsync-android (SAF/path mirror).
HSYNCFOLDER_FILENAME = ".hsyncfolder"

# Environment override for the installation state directory (ADR-0025). It
# holds the server's per-bucket state subdir and, by default, is the parent of
# the client device dir. Consumers: hsync-client, hsync-server, tests.
HSYNC_STATE_DIR_ENV = "HSYNC_STATE_DIR"

# Explicit, process-wide sync-state database path override. When set, the
# client and the server open this single DB instead of the per-folder /
# per-bucket layout. Consumers: hsync-client (state_backend), hsync-server
# (config), tests.
HSYNC_STATE_DB_ENV = "HSYNC_STATE_DB"

# Per-device / per-server sync-state layout names (ADR-0025). Consumers:
# hsync-client (state_backend), hsync-server (config), tests.
SYNCSTATE_DIRNAME = "syncstate"
SERVER_STATE_SUBDIR = "server"
STATE_INDEX_DB_FILENAME = "index.db"
AUTH_DB_FILENAME = "auth.db"

# Legacy engine-owned basenames. Causal state no longer lives in these files
# (ADR-0025) but they stay rejected on the wire and by the ignore matcher so
# an old peer cannot plant them through the sync channel.
HSYNCTOMBSTONES_FILENAME = ".hsynctombstones"
HSYNCSTATE_FILENAME = ".hsyncstate"

# =============================================================================
# File Transfer Settings
# =============================================================================

# Read chunk sizes by file size. The tiers bound the per-transfer buffer, so
# they only need to grow when the per-iteration Python overhead (frame read,
# throttle wrapper, hash update, write) becomes material relative to the bytes
# in flight. Measured on the HTTPS apply path: at 8 KiB a 200 KiB file paid 26
# Python-level iterations and cost 5.5 ms CPU/file (incompressible payload);
# at 256 KiB the same file is read in a single iteration and costs 4.3 ms/file
# (~-20%). Above ~1 MiB the transfer itself (TLS + hashing + writes) dominates
# and the chunk size measured neutral, so the upper tiers exist only to keep
# the worst-case buffering bounded (see below).
#
# Note: the end-to-end LAN burst probe could NOT resolve this saving, because
# that path spends ~15 ms CPU/file for reasons not yet attributed (see
# hsync-client/docs/internal/testing.md). The isolated per-file reduction is
# real; the end-to-end gain is not measurable until that overhead is understood.
#
# Worst-case buffering = CHUNK_SIZE_LARGE * MAX_CONCURRENT_TRANSFERS (default
# concurrency 5 -> 5 MiB), which keeps the NAS target comfortable.
CHUNK_SIZE_SMALL = 256 * 1024  # 256KB for files < 1MB (one read per file)
CHUNK_SIZE_MEDIUM = 512 * 1024  # 512KB for files < 100MB
CHUNK_SIZE_LARGE = 1024 * 1024  # 1MB for files >= 100MB

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

# Higher threshold for p2p mode: on gigabit links with slow CPUs (e.g. NAS ARM)
# the signature computation cost can exceed the bandwidth saving, so delta is
# only attempted for larger files (same rationale as the LAN compression floor).
DELTA_MIN_FILE_SIZE_P2P = 1024 * 1024  # 1 MB

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

# Maximum WebSocket text-frame size accepted by every peer. HSYNC frames
# carry ONLY structured metadata (auth frames, file events, presence), never
# bulk content: a legitimate frame is tens of KB at most. The value is twice
# the websockets library default (max_size = 1 MiB), giving comfortable head
# room for the largest auth frame (token + capabilities + vclock) while
# halving the worst-case memory cost of a hostile giant frame versus 4 MiB.
# SSOT: both hsync-client and hsync-server import it from here.
WS_MAX_MESSAGE_BYTES = 2 * 1024 * 1024  # 2 MiB

# TOCTOU re-hash threshold: files smaller than this get a full SHA-256 re-hash
# after the rolling scan to detect content changes that mtime+size alone miss.
# 10 MB is a reasonable cutoff — re-hashing is fast enough to not impact UX.
DELTA_TOCTOU_REHASH_THRESHOLD = 10 * 1024 * 1024  # 10 MB

# =============================================================================
# Clock Synchronisation (NTP)
# =============================================================================

# Default public SNTP servers probed in order during LAN/offline startup until
# one answers. Overridable via the HSYNC_NTP_HOSTS environment variable (comma-
# separated list), consumed by every HSYNC project (hsync-client,
# hsync-desktop via the client subprocess, hsync-android mirror).
NTP_DEFAULT_HOSTS: tuple[str, ...] = (
    "pool.ntp.org",
    "time.cloudflare.com",
    "time.google.com",
)

# SNTP server port (RFC 4330).
NTP_PORT = 123

# Default UDP port of the boot/1 bootstrap listener (boot-1.md §Transport).
# Single SSOT shared by the hsync-bootnode CLI (`--port` default) and the
# hsync-client bare-host default, so the two can never drift.
BOOT_DEFAULT_PORT = 443

# Default TCP port of the sync server (HTTPS/WSS) when an endpoint carries no
# explicit port. Single SSOT shared by the hsync-server ``Settings.port``
# default, the hsync-client bare-host CLI and the hsync-desktop endpoint
# grammar / trust pre-flight.
SERVER_DEFAULT_PORT = 9753

# Recommended ordered UDP port set for the boot/1 listener (opt-in multi-port;
# the default remains the single BOOT_DEFAULT_PORT). First = canonical QUIC/HTTP3
# (443, usually allowed); second = DNS (53, the most permissive UDP port, but
# often hijacked by a local resolver). ADVISORY: neither side applies it by
# default — the operator enables it explicitly with hsync-bootnode `--ports`
# and the hsync-client `HSYNC_BOOTNODE_PORTS`; both sides must agree on the set.
BOOT_PORT_SET = (BOOT_DEFAULT_PORT, 53)

# Seconds to wait for a single SNTP probe before moving to the next host.
NTP_TIMEOUT_SECONDS = 3.0

# Number of SNTP round-trips per host, median of which is the offset estimate.
NTP_PROBES_PER_HOST = 3

# Wire-level guard: a peer-supplied ``corrected_mtime`` farther than this in the
# future relative to the receiver's corrected clock is clamped, so a malicious
# or wildly mis-set peer cannot win every mtime tie-break (conflict
# engineering). Mirrored by the Android client.
CORRECTED_MTIME_MAX_FUTURE_SKEW = 300

# Content-identical files whose corrected mtimes differ by more than this are
# metadata-divergent: the engine still propagates the newer mtime (a plain
# ``touch``) without transferring content. Small enough to converge normal
# sub-second writes, large enough to absorb filesystem timestamp granularity.
# Mirrored by the Android client.
MTIME_PROPAGATION_TOLERANCE_SECONDS = 1
