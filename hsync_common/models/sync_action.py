"""
Sync action model for HSYNC.

This module defines the SyncAction class and SyncActionName enum
for representing synchronization decisions (upload, download, delete, or no action).
"""

from __future__ import annotations

from datetime import timedelta as td
from enum import StrEnum

from .file import File
from .symlink import Symlink


class SyncActionName(StrEnum):
    """
    Enumeration of possible synchronization actions.

    Values:
        download: File should be downloaded from server (remote is newer).
        upload: File should be uploaded to server (local is newer).
        delete: File should be deleted locally (not present on server in p2p mode).
        delete_remote: File should be deleted on the server/master (a local
            tombstone says it was deleted here while offline; it must not be
            resurrected by downloading it back).
        upload_symlink: A local symlink (target inside the bucket) should be
            replicated structurally to the remote — the (path, target) pair,
            never the target's content.
        download_symlink: A remote symlink (target inside the bucket) should be
            recreated locally as a link — the (path, target) pair, never the
            target's content.
        nothing: No action needed (files are in sync).
    """

    download = "download"
    upload = "upload"
    delete = "delete"
    delete_remote = "delete_remote"
    upload_symlink = "upload_symlink"
    download_symlink = "download_symlink"
    nothing = "nothing"


class SyncAction:
    """
    Represents a synchronization action for a file or symlink.

    Attributes:
        file: The File or Symlink object this action applies to.
        name: The type of action (download, upload, delete, nothing).
        timedelta: Human-readable time difference string.
        conflict: True when the action overwrites a locally-modified file that
            could not be reconciled automatically (same mtime, different
            content); signals that the local copy should be preserved first.
        tombstone_confirmed: True when the deletion is backed by a matching
            tombstone marker (the file was deleted elsewhere while this peer
            was offline). The mass-deletion guard exempts these deletions
            because a tombstone is positive proof the removal is intentional,
            not a transient empty-bucket artefact.
    """

    def __init__(
        self,
        file: File | Symlink,
        name: SyncActionName | None = None,
        timedelta: int = 0,
        conflict: bool = False,
        tombstone_confirmed: bool = False,
        permissions_only: bool = False,
    ):
        self.file: File | Symlink = file
        self.name = name
        self.timedelta = self._format_timedelta(timedelta)
        self.conflict = conflict
        self.tombstone_confirmed = tombstone_confirmed
        self.permissions_only = permissions_only

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"file={self.file}, "
            f"name={self.name}, "
            f"timedelta={self.timedelta}, "
            f"conflict={self.conflict}, "
            f"tombstone_confirmed={self.tombstone_confirmed}, "
            f"permissions_only={self.permissions_only})"
        )

    def to_dict(self) -> dict:
        """Convert the SyncAction instance to a dictionary.

        Includes ``conflict`` and ``tombstone_confirmed``: dropping either
        would silently lose a signal for any consumer that serializes the
        action instead of reading attributes.
        """
        return {
            "file": self.file.to_dict(),
            "name": self.name,
            "timedelta": self.timedelta,
            "conflict": self.conflict,
            "tombstone_confirmed": self.tombstone_confirmed,
            "permissions_only": self.permissions_only,
        }

    def _format_timedelta(self, delta_seconds: int) -> str:
        """Format a time delta in seconds to a human-readable string."""
        delta = td(seconds=delta_seconds)
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if seconds > 0:
            parts.append(f"{seconds}s")

        return " ".join(parts) if parts else "0s"
