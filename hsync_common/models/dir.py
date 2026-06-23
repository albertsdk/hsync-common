"""
Directory model for HSYNC.

This module defines the Dir class representing a directory with its
path and permissions, used for directory synchronization events.
"""

from pathlib import Path
from typing import Optional

from hsync_common.permissions import get_permissions


def _is_hidden_dir_basic(directory: str) -> bool:
    """Pure dot-prefix hidden-directory check (no ignore rules).

    A directory is considered hidden if its name, or its immediate parent's
    name, starts with a dot. This is the legacy detection used as the
    fallback inside :class:`hsync_common.ignore.IgnoreMatcher`; keeping it
    separate from :func:`is_hidden_dir` avoids infinite recursion when a
    matcher is active.
    """
    path = Path(directory.rstrip("/"))
    if path.name.startswith("."):
        return True
    parent = path.parent
    return parent != path and parent.name.startswith(".")


def is_hidden_dir(directory: str) -> bool:
    """
    Check if a directory must be excluded from synchronisation.

    When a process-wide :class:`hsync_common.ignore.IgnoreMatcher` is active
    (installed by the client at startup) it is consulted so that
    ``.hsyncignore`` rules and extra patterns are honoured. When no matcher
    is installed (e.g. on the server) the legacy dot-prefix detection is used,
    preserving the previous behaviour.

    Args:
        directory: Path to the directory.

    Returns:
        True if the directory is hidden/ignored, False otherwise.
    """
    from hsync_common.ignore import get_active_matcher

    matcher = get_active_matcher()
    if matcher is not None:
        return matcher.matches(directory, is_dir=True)
    return _is_hidden_dir_basic(directory)


class Dir:
    """
    Represents a directory with path and permissions.

    This class is used to track directory metadata for synchronization
    events, including creation, modification, and deletion of directories.

    Attributes:
        path: Absolute or relative path to the directory.
        permissions: Octal permission string (e.g., '755').
    """

    def __init__(self, path: str | None = None, permissions: str | None = None):
        """
        Initialize a Dir instance.

        Args:
            path: Path to the directory.
            permissions: Octal permission string.
        """
        self.path = path
        self.permissions = permissions

    def __repr__(self) -> str:
        """Return string representation of the Dir instance."""
        return f"{self.__class__.__name__}(path={self.path}, permissions={self.permissions})"

    @staticmethod
    def _get_permissions(obj_path: str) -> str:
        """Get permissions for a path as a canonical octal string."""
        return get_permissions(obj_path)

    def to_dict(self) -> dict:
        """Convert the Dir instance to a dictionary."""
        return {
            "path": self.path,
            "permissions": self.permissions,
        }

    @classmethod
    def from_dict(cls, data: dict, localpath: str, strip_localpath: bool = False) -> "Dir":
        """
        Create a Dir instance from a dictionary.

        Args:
            data: Dictionary containing 'path' and optionally 'permissions'.
            localpath: Base path for resolving relative paths.
            strip_localpath: If True, remove localpath prefix from path.

        Returns:
            New Dir instance.
        """
        data_path = data.get("path", "")
        path = (
            str(data_path).removeprefix(localpath).lstrip("/")
            if strip_localpath
            else str(Path(localpath) / str(data_path).lstrip("/"))
        )
        return cls(
            path=path,
            permissions=data.get("permissions"),
        )

    @classmethod
    def get(cls, path: str, buckets_dir: str | None = None) -> Optional["Dir"]:
        """
        Get a Dir instance for an existing directory.

        Args:
            path: Path to the directory.
            buckets_dir: Optional base directory to prepend.

        Returns:
            Dir instance if directory exists, None otherwise.
        """
        path = str(Path(buckets_dir) / path.lstrip("/")) if buckets_dir else path
        if Path(path).exists():
            return cls(
                path=path,
                permissions=cls._get_permissions(path),
            )
        else:
            return None
