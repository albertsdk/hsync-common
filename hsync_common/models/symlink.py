"""
Symlink model for HSYNC.

This module defines the Symlink class for representing symbolic links
that need to be synchronized between client and server.
"""

from os import readlink
from os import stat as os_stat
from os.path import basename, exists, islink
from typing import Optional


class Symlink:
    """
    Represents a symbolic link for synchronization.

    Attributes:
        filepath: Path to the symlink.
        name: Name of the symlink (filename only).
        target: Path that the symlink points to.
        ctime: Creation time (Unix timestamp).
        mtime: Modification time (Unix timestamp).
    """

    def __init__(
        self,
        filepath: str,
        target: str | None = None,
        name: str | None = None,
        ctime: float | None = None,
        mtime: float | None = None,
    ):
        self.filepath = filepath
        self.name = name or basename(filepath)
        self.target = target
        self.ctime = ctime
        self.mtime = mtime

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"filepath={self.filepath}, "
            f"name={self.name}, "
            f"target={self.target})"
        )

    @classmethod
    def get(cls, filepath: str) -> Optional["Symlink"]:
        """Create a Symlink instance from a filesystem path."""
        if not exists(filepath) and not islink(filepath):
            return None

        if not islink(filepath):
            return None

        try:
            stat = os_stat(filepath, follow_symlinks=False)
            target = readlink(filepath)

            return cls(
                filepath=filepath,
                name=basename(filepath),
                target=target,
                ctime=stat.st_ctime,
                mtime=stat.st_mtime,
            )
        except OSError:
            return None

    def to_dict(self) -> dict:
        """Convert the Symlink instance to a dictionary."""
        return {
            "type": "symlink",
            "filepath": self.filepath,
            "name": self.name,
            "target": self.target,
            "ctime": self.ctime,
            "mtime": self.mtime,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Symlink":
        """Create a Symlink instance from a dictionary."""
        return cls(
            filepath=data.get("filepath", ""),
            name=data.get("name"),
            target=data.get("target"),
            ctime=data.get("ctime"),
            mtime=data.get("mtime"),
        )
