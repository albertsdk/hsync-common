# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Free-space guards shared by every HSYNC receiver.

Both sides of a transfer must refuse a write that would break the configured
free-space reserve: the server before spooling an upload, and the client before
starting a download (or the LAN master before accepting one). The *rule* — free
space must cover the reserve plus the bytes about to be written — is the same
everywhere; only the reaction differs (HTTP 507, logged skip, raised error).

:func:`check_free_space` owns the rule and returns a decision object, so a
change to the formula cannot leave one receiver behind. It takes the reserve in
**bytes** — the unit ``shutil.disk_usage`` reports and the unit every consumer
stores — and one operator surface exists for it: a human-readable size string
(``"500MB"``) parsed by :func:`hsync_common.format.parse_size` into those bytes
(``--min-free-disk-space`` for the client, ``HSYNC_MIN_FREE_DISK_SPACE`` for the
server, the settings field for the desktop and WD OS5).

Consumers: ``hsync-server`` (``api/utils.py::ensure_disk_space``),
``hsync-client`` (``transfer.py`` download guard, ``p2p_server.py`` upload
guard, ``main_logic.py`` startup check), shared tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from shutil import disk_usage

__all__ = [
    "BYTES_PER_MB",
    "FreeSpaceCheck",
    "check_free_space",
]

BYTES_PER_MB = 1024 * 1024  # consumers: hsync-desktop (MB spin-box bounds), tests


@dataclass(frozen=True, slots=True)
class FreeSpaceCheck:
    """Outcome of a free-space probe.

    Attributes:
        ok: Whether the write may proceed. Always ``True`` when the guard is
            disabled (``reserve_bytes <= 0``) or when the probe itself failed —
            an unreadable path is a warning, never a rejection.
        free_bytes: Free space reported by the probe (``0`` when it failed).
        required_bytes: Reserve plus the incoming payload, in bytes.
        error: The ``OSError`` text when the probe failed, else ``None``;
            callers log it as a warning.
    """

    ok: bool
    free_bytes: int
    required_bytes: int
    error: str | None

    @property
    def free_mb(self) -> int:
        """Free space in whole MB (for operator-facing messages)."""
        return int(self.free_bytes / BYTES_PER_MB)

    @property
    def required_mb(self) -> int:
        """Required space in whole MB (for operator-facing messages)."""
        return int(self.required_bytes / BYTES_PER_MB)


def check_free_space(
    path: str,
    *,
    reserve_bytes: int = 0,
    incoming_bytes: int = 0,
) -> FreeSpaceCheck:
    """Decide whether *path*'s filesystem can hold a write.

    Args:
        path: Filesystem location the write targets (a directory, or any path
            on the filesystem — ``disk_usage`` resolves to its mount).
        reserve_bytes: Free space to keep spare, in bytes. ``<= 0`` disables the
            check (returns ``ok=True`` without probing).
        incoming_bytes: Payload about to be written. ``0`` checks the reserve
            alone (startup guard).

    Returns:
        The :class:`FreeSpaceCheck` decision; never raises on a probe failure.
    """
    if reserve_bytes <= 0:
        return FreeSpaceCheck(ok=True, free_bytes=0, required_bytes=0, error=None)
    required = reserve_bytes + max(incoming_bytes, 0)
    try:
        free = disk_usage(path).free
    except OSError as exc:
        return FreeSpaceCheck(ok=True, free_bytes=0, required_bytes=required, error=str(exc))
    return FreeSpaceCheck(
        ok=free >= required,
        free_bytes=free,
        required_bytes=required,
        error=None,
    )
