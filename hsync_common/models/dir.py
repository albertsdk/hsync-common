"""
Directory model for HSYNC.

This module defines the Dir class representing a directory with its
path and permissions, used for directory synchronization events.
"""

from os import stat as os_stat
from pathlib import Path
from typing import Optional

from hsync_common.permissions import mode_to_octal


def is_hidden_dir(directory: str) -> bool:
    """
    Check if a directory must be excluded from synchronisation.

    When a process-wide :class:`hsync_common.ignore.IgnoreMatcher` is active
    (installed by the client at startup) it is consulted so that
    ``.hsyncignore`` rules and extra patterns are honoured. When no matcher
    is installed (e.g. on the server) the built-in default ignore patterns
    (:data:`hsync_common.constants.DEFAULT_IGNORE_PATTERNS`) are used.

    Following the industry standard (Syncthing, rsync, Nextcloud, OneDrive),
    dotfile directories in general (``.git/``, ``.config/`` …) are **not**
    excluded: only OS cache directories and editor/office temporary files are
    filtered by default.

    Args:
        directory: Path to the directory.

    Returns:
        True if the directory is ignored, False otherwise.
    """
    from hsync_common.ignore import should_skip

    return should_skip(directory, is_dir=True)


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
        from hsync_common.models import _resolve_prefixed_path

        path = _resolve_prefixed_path(data.get("path", ""), localpath, strip=strip_localpath)
        return cls(
            path=path,
            permissions=data.get("permissions"),
        )

    @classmethod
    def get(cls, path: str, buckets_dir: str | None = None) -> Optional["Dir"]:
        """
        Get a Dir instance for an existing directory.

        A directory can disappear concurrently with a sync scan; any
        :class:`OSError` raised by the stat/read degrades to ``None`` instead
        of aborting the whole sync cycle.

        Args:
            path: Path to the directory.
            buckets_dir: Optional base directory to prepend.

        Returns:
            Dir instance if directory exists, None otherwise.
        """
        path = str(Path(buckets_dir) / path.lstrip("/")) if buckets_dir else path
        try:
            # Single stat: the mode is read from the same stat object used for
            # the existence check — one syscall instead of exists() + get_permissions
            # (which would stat a second time). A missing path raises ENOENT here,
            # exactly like Path.exists() would have returned False.
            st = os_stat(path)
        except OSError:
            return None
        return cls(
            path=path,
            permissions=mode_to_octal(st.st_mode),
        )
