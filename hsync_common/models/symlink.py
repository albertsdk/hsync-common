"""
Symlink model for HSYNC.

This module defines the Symlink class for representing symbolic links
that need to be synchronized between client and server.
"""

from __future__ import annotations

from os import readlink
from os import stat as os_stat
from pathlib import Path


class Symlink:
    """
    Represents a symbolic link for synchronization.

    Attributes:
        filepath: Bucket-relative path (after ``from_dict`` with prefix) or
            absolute path (from ``get``). Always absolute after ``get`` is
            called with a ``dir_prefix``.
        name: Name of the symlink (filename only).
        target: Path that the symlink points to.
        ctime: Creation time as integer Unix timestamp.
        mtime: Modification time as integer Unix timestamp.
    """

    def __init__(
        self,
        filepath: str,
        target: str | None = None,
        name: str | None = None,
        ctime: int | None = None,
        mtime: int | None = None,
    ):
        self.filepath = filepath
        self.name = name or Path(filepath).name
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
    def get(cls, filepath: str, dir_prefix: str | None = None) -> Symlink | None:
        """Create a Symlink instance from a filesystem path.

        When *dir_prefix* is given the *filepath* is first made absolute
        relative to it (matching ``File.get``). The returned ``filepath`` is
        always absolute.
        """
        filepath = str(Path(dir_prefix) / filepath.lstrip("/")) if dir_prefix else filepath

        if not Path(filepath).is_symlink():
            return None

        try:
            stat = os_stat(filepath, follow_symlinks=False)
            target = readlink(filepath)

            return cls(
                filepath=filepath,
                name=Path(filepath).name,
                target=target,
                ctime=int(stat.st_ctime),
                mtime=int(stat.st_mtime),
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
    def from_dict(
        cls,
        data: dict,
        dir_prefix: str | None = None,
        strip_dir_prefix: bool = True,
    ) -> Symlink:
        """Create a Symlink instance from a dictionary.

        The ``dir_prefix`` / ``strip_dir_prefix`` parameters mirror
        :meth:`File.from_dict`: when *strip_dir_prefix* is True the prefix is
        stripped from the dict's ``filepath`` (making it bucket-relative);
        when False the prefix is prepended (making it absolute).
        """
        if strip_dir_prefix and not dir_prefix:
            raise ValueError("Set dir_prefix to strip it.")

        data_filepath = data.get("filepath", "")
        if strip_dir_prefix and dir_prefix:
            filepath = str(data_filepath).removeprefix(dir_prefix).lstrip("/")
        elif dir_prefix:
            filepath = str(Path(dir_prefix) / str(data_filepath).lstrip("/"))
        else:
            filepath = str(data_filepath)

        return cls(
            filepath=filepath,
            name=data.get("name"),
            target=data.get("target"),
            ctime=int(data["ctime"]) if data.get("ctime") is not None else None,
            mtime=int(data["mtime"]) if data.get("mtime") is not None else None,
        )
