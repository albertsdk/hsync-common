# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""User-facing defaults and accepted bounds shared by the CLI and the desktop GUI.

The desktop shells out to ``hsync`` and cannot import the client package, so
every value it mirrors used to be a copy — and a copied default is a silent
behavioural divergence waiting to happen. These values are the single
definition; ``hsync_client.constants`` and ``hsync_desktop.config`` re-export
them under their own names.

Both the default and the accepted range of a user-facing knob live here: the CLI
validates against the bounds and the GUI clamps to them, so a value the GUI
emits is always accepted by the CLI. GUI-only guardrails (e.g. a taller minimum
than the CLI allows) stay in ``hsync_desktop/config.py``, documented as such.

Consumers: ``hsync-client`` (CLI flag defaults and validation, config/env
fallbacks), ``hsync-desktop`` (settings defaults, spin-box ranges and the flags
it emits), tests.
"""

from __future__ import annotations

__all__ = [
    "BANDWIDTH_MAX_BPS",
    "BANDWIDTH_MIN_BPS",
    "HTTP_TIMEOUT_DEFAULT",
    "HTTP_TIMEOUT_MAX",
    "HTTP_TIMEOUT_MIN",
    "MASS_DELETE_GUARD_DEFAULT",
    "MASS_DELETE_PERCENT_DEFAULT",
    "MASS_DELETE_THRESHOLD_DEFAULT",
    "MAX_CONCURRENT_TRANSFERS_DEFAULT",
    "MAX_CONCURRENT_TRANSFERS_MAX",
    "MAX_CONCURRENT_TRANSFERS_MIN",
    "MAX_INBOUND_SIZE_MB_DEFAULT",
    "MAX_INBOUND_SIZE_MB_MAX",
    "MAX_INBOUND_SIZE_MB_MIN",
    "MAX_WAIT_TIMEOUT_DEFAULT",
    "MAX_WAIT_TIMEOUT_MAX",
    "MAX_WAIT_TIMEOUT_MIN",
    "MIN_FREE_DISK_SPACE_DEFAULT",
    "MIN_FREE_DISK_SPACE_MAX",
    "MIN_FREE_DISK_SPACE_MIN",
    "P2P_PEER_DOWNLOAD_DEFAULT",
    "P2P_PEER_READ_CAP_DEFAULT",
    "P2P_PEER_READ_CAP_MAX",
    "P2P_PEER_READ_CAP_MIN",
    "P2P_PEER_SOURCES_MAX_DEFAULT",
    "P2P_PEER_SOURCES_MAX_MAX",
    "P2P_PEER_SOURCES_MAX_MIN",
    "RECONNECT_DELAY_DEFAULT",
    "RECONNECT_DELAY_MAX",
    "RECONNECT_DELAY_MIN",
    "RESYNC_MAX",
    "RESYNC_MIN",
    "STABILITY_DELAY_DEFAULT",
    "STABILITY_DELAY_MAX",
    "STABILITY_DELAY_MIN",
    "SYNC_DIRECTION_DEFAULT",
]

# Seconds allowed for one HTTP request (connect + read) before retrying.
HTTP_TIMEOUT_DEFAULT = 30
HTTP_TIMEOUT_MIN = 1
HTTP_TIMEOUT_MAX = 300

# Seconds between file size/mtime checks before a file counts as stable.
STABILITY_DELAY_DEFAULT = 5
STABILITY_DELAY_MIN = 1
STABILITY_DELAY_MAX = 60

# Upper bound (seconds) on how long one upload slot may be held waiting for a
# writer to finish. The wait ends as soon as size+mtime settle, so a large file
# is not penalised: if it is still being written at the cap the upload is
# deferred and retried, and it completes right after the write ends. Keeping the
# cap short bounds how long a pooled transfer slot can be parked by a file that
# never settles (logs, VM images, in-progress downloads); raising it multiplies
# that cost without improving completion latency.
MAX_WAIT_TIMEOUT_DEFAULT = 120
MAX_WAIT_TIMEOUT_MIN = 10
MAX_WAIT_TIMEOUT_MAX = 3600

# Seconds between reconnect attempts after a transport failure.
RECONNECT_DELAY_DEFAULT = 5
RECONNECT_DELAY_MIN = 1
RECONNECT_DELAY_MAX = 60

# Periodic safety-net resync: disabled (0) or a bounded interval.
RESYNC_MIN = 20
RESYNC_MAX = 3600

# Canonical default direction of a sync pair.
SYNC_DIRECTION_DEFAULT = "bidirectional"

# Parallel file transfers (downloads/uploads) per peer.
MAX_CONCURRENT_TRANSFERS_DEFAULT = 5
MAX_CONCURRENT_TRANSFERS_MIN = 1
MAX_CONCURRENT_TRANSFERS_MAX = 20

# Mass-deletion guard: pause deletions above this absolute count / percentage.
MASS_DELETE_GUARD_DEFAULT = True
MASS_DELETE_THRESHOLD_DEFAULT = 50
MASS_DELETE_PERCENT_DEFAULT = 50

# Free-space pre-flight (bytes) and the absolute per-file inbound cap (MB).
# The reserve is bytes because that is what ``shutil.disk_usage`` reports and
# what both receivers store; the operator-facing surfaces (CLI flag, server
# env var, WD OS5 form) accept a human-readable size string parsed by
# ``hsync_common.format.parse_size``.
MIN_FREE_DISK_SPACE_DEFAULT = 500 * 1024 * 1024  # 500 MiB
MIN_FREE_DISK_SPACE_MIN = 0  # 0 = disabled
MIN_FREE_DISK_SPACE_MAX = 100 * 1024 * 1024 * 1024  # 100 GiB
MAX_INBOUND_SIZE_MB_DEFAULT = 10_240
MAX_INBOUND_SIZE_MB_MIN = 0
MAX_INBOUND_SIZE_MB_MAX = 10_000_000

# Bandwidth limit bounds accepted by the CLI and enforced by the GUI fields.
BANDWIDTH_MIN_BPS = 1024
BANDWIDTH_MAX_BPS = 100 * 1024 * 1024

# Download file blocks from other peers in p2p mode, and the caps that bound it.
P2P_PEER_DOWNLOAD_DEFAULT = True
P2P_PEER_READ_CAP_DEFAULT = 2
P2P_PEER_READ_CAP_MIN = 1
P2P_PEER_READ_CAP_MAX = 32
P2P_PEER_SOURCES_MAX_DEFAULT = 3
P2P_PEER_SOURCES_MAX_MIN = 1
P2P_PEER_SOURCES_MAX_MAX = 8
