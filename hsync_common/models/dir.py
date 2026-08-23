"""
Directory model for HSYNC.

This module defines the Dir class representing a directory with its
path and permissions, used for directory synchronization events.
"""

from os import stat as os_stat
from pathlib import Path

from hsync_common.permissions import mode_to_octal

from ._util import _resolve_prefixed_path


def is_hidden_dir(directory: str) -> bool:
    """Return True when *directory* must be excluded from synchronisation.

    See :func:`hsync_common.ignore.should_skip` for the filtering rules
    (active IgnoreMatcher, then built-in default patterns).
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
        recursive: When a ``deleted`` event carries this flag, the directory
            deletion applies recursively: every descendant is removed along
            with the directory itself (a single message replaces one
            per-descendant message).
    """

    def __init__(
        self,
        path: str | None = None,
        permissions: str | None = None,
        recursive: bool | None = None,
    ):
        """
        Initialize a Dir instance.

        Args:
            path: Path to the directory.
            permissions: Octal permission string.
            recursive: Whether the directory event is recursive (deletion only).
        """
        self.path = path
        self.permissions = permissions
        self.recursive = recursive

    def __repr__(self) -> str:
        """Return string representation of the Dir instance."""
        return f"{self.__class__.__name__}(path={self.path}, permissions={self.permissions})"

    def to_dict(self) -> dict:
        """Convert the Dir instance to a dictionary.

        The ``recursive`` key is emitted only when set (truthy) so
        non-recursive events keep the historical wire shape.
        """
        data: dict[str, object] = {
            "path": self.path,
            "permissions": self.permissions,
        }
        if self.recursive:
            data["recursive"] = True
        return data

    @classmethod
    def from_dict(cls, data: dict, localpath: str, strip_localpath: bool = False) -> "Dir":
        """
        Create a Dir instance from a dictionary.

        Args:
            data: Dictionary containing 'path', optionally 'permissions' and
                'recursive'.
            localpath: Base path for resolving relative paths.
            strip_localpath: If True, remove localpath prefix from path.

        Returns:
            New Dir instance.
        """
        path = _resolve_prefixed_path(data.get("path", ""), localpath, strip=strip_localpath)
        return cls(
            path=path,
            permissions=data.get("permissions"),
            recursive=bool(data.get("recursive", False)) or None,
        )

    @classmethod
    def get(cls, path: str, buckets_dir: str | None = None) -> "Dir | None":
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
