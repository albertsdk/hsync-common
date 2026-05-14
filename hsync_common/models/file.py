"""
File model for HSYNC.

This module defines the File class representing a file with its metadata
(path, timestamps, size, checksum, permissions) used for file synchronization.
"""

import stat
from datetime import UTC, datetime
from hashlib import md5
from os import stat as os_stat
from os.path import basename, exists, getctime, getmtime, getsize, join
from re import match
from typing import Optional, TypedDict

from hsync_common.constants import (
    CHUNK_SIZE_LARGE,
    CHUNK_SIZE_MEDIUM,
    CHUNK_SIZE_SMALL,
    FILE_SIZE_MEDIUM,
    FILE_SIZE_SMALL,
    HSYNCKEEP_FILENAME,
)

# =============================================================================
# MD5 Cache
# =============================================================================

# In-memory cache for MD5 checksums to avoid redundant computation
# during a single sync operation. Key: filepath, Value: tuple[md5sum, mtime]
_md5_cache: dict[str, tuple[str, int]] = {}


def clear_md5_cache() -> None:
    """Clear the entire MD5 cache.

    Should be called at the start of each sync cycle to ensure
    fresh checksums are computed for all files.
    """
    _md5_cache.clear()


def invalidate_md5_cache(file_path: str) -> None:
    """Remove a single entry from the MD5 cache.

    Should be called when a file is known to have been modified
    (e.g. after a download, upload, or watchdog event) so that
    the next ``File.get()`` recomputes the checksum.

    Args:
        file_path: Path of the file to invalidate.
    """
    _md5_cache.pop(file_path, None)


def _get_cached_md5(file_path: str, current_mtime: int) -> str | None:
    """Get cached MD5 if file hasn't been modified."""
    if file_path in _md5_cache:
        cached_md5, cached_mtime = _md5_cache[file_path]
        if cached_mtime == current_mtime:
            return cached_md5
        del _md5_cache[file_path]
    return None


def _set_cached_md5(file_path: str, md5sum: str, mtime: int) -> None:
    """Store MD5 in cache with its mtime for invalidation."""
    _md5_cache[file_path] = (md5sum, mtime)


# =============================================================================
# TypedDicts for type-safe serialization
# =============================================================================


class FileDict(TypedDict):
    """Type-safe dictionary representation of a File."""

    filepath: str | None
    name: str | None
    ctime: int | None
    mtime: int | None
    size: int
    md5sum: str | None
    permissions: str | None


def is_hidden_file(file_path: str) -> bool:
    """
    Check if a file should be considered hidden and excluded from sync.

    Matches various patterns for hidden, temporary, and backup files:
    - ^\\..* : Files starting with a dot (Unix hidden files)
    - .*~$ : Emacs/editor backup files ending with tilde
    - ^4913$ : Vim temporary file identifier
    - ^\\..*\\.sw[px]$ : Vim swap files (.swp, .swo)
    - ^\\.~lock\\..*#$ : LibreOffice lock files
    - .*\\.bak$ : Common backup files ending with .bak
    - .*\\.tmp$ : Temporary files ending with .tmp
    - .*\\.temp$ : Temporary files ending with .temp
    - .*\\.swp$ : Swap files ending with .swp
    - .*\\.swo$ : Swap files ending with .swo
    - .*-\\d{4}-\\d{2}-\\d{2}-\\d{6}$ : Date-timestamped backups

    Args:
        file_path: Path to the file to check.

    Returns:
        True if the file matches any hidden file pattern, False otherwise.
    """
    name = basename(file_path)

    # Sentinel file for empty-directory sync — never hidden
    if name == HSYNCKEEP_FILENAME:
        return False

    hidden_file_regex = (
        r"(^\..*|.*~$|^4913$|^\..*\.sw[px]$|^\.~lock\..*#$|"
        r".*\.bak$|.*\.tmp$|.*\.temp$|.*\.swp$|.*\.swo$|"
        r".*-\d{4}-\d{2}-\d{2}-\d{6}$)"
    )
    return bool(match(hidden_file_regex, name))



class File:
    """
    Represents a file with its metadata for synchronization.

    Attributes:
        filepath: Full path to the file.
        name: Base name of the file.
        ctime: Creation time as Unix timestamp.
        mtime: Modification time as Unix timestamp.
        size: File size in bytes.
        md5sum: MD5 checksum of file content.
        permissions: Symbolic permission string (e.g., '-rw-r--r--').
    """

    def __init__(
        self,
        filepath: str | None = None,
        ctime: str | int | float | datetime | None = None,
        mtime: str | int | float | datetime | None = None,
        size: int = 0,
        md5sum: str | None = None,
        permissions: str | None = None,
    ):
        self.filepath = filepath
        self.name = basename(filepath) if filepath else None
        self.size = size
        self.md5sum = md5sum
        self.permissions = permissions
        self.ctime = self._parse_time(ctime)
        self.mtime = self._parse_time(mtime)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"filepath={self.filepath}, "
            f"name={self.name}, "
            f"ctime={self.ctime}, "
            f"mtime={self.mtime}, "
            f"size={self.size}, "
            f"md5sum={self.md5sum}, "
            f"permissions={self.permissions})"
        )

    def _parse_time(self, time: str | int | float | datetime | None) -> int | None:
        """Parse various time formats to Unix timestamp."""
        if isinstance(time, datetime):
            return int(time.timestamp())
        elif isinstance(time, str):
            return int(datetime.fromisoformat(time).timestamp())
        elif isinstance(time, int | float):
            return int(datetime.fromtimestamp(time, UTC).timestamp())
        return None

    @staticmethod
    def _compute_md5(filepath: str, file_size: int | None = None) -> str:
        """Compute the MD5 checksum of a file with adaptive chunk size."""
        if file_size is not None:
            if file_size >= FILE_SIZE_MEDIUM:
                chunk_size = CHUNK_SIZE_LARGE
            elif file_size >= FILE_SIZE_SMALL:
                chunk_size = CHUNK_SIZE_MEDIUM
            else:
                chunk_size = CHUNK_SIZE_SMALL
        else:
            chunk_size = CHUNK_SIZE_SMALL

        hash_md5 = md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    @staticmethod
    def _get_permissions(obj_path: str) -> str:
        """Get file permissions in symbolic notation."""
        obj_stat = os_stat(obj_path)
        return stat.filemode(obj_stat.st_mode)

    def to_dict(self) -> FileDict:
        """Convert the File instance to a FileDict."""
        return FileDict(
            filepath=self.filepath,
            name=self.name,
            ctime=self.ctime,
            mtime=self.mtime,
            size=self.size,
            md5sum=self.md5sum,
            permissions=self.permissions,
        )

    @classmethod
    def get(cls, file_path: str, buckets_dir: str | None = None) -> Optional["File"]:
        """Get a File instance for an existing file."""
        file_path = join(buckets_dir, file_path.lstrip("/")) if buckets_dir else file_path
        if exists(file_path):
            file_size = getsize(file_path)
            file_mtime = int(getmtime(file_path))

            md5sum = _get_cached_md5(file_path, file_mtime)
            if md5sum is None:
                md5sum = cls._compute_md5(file_path, file_size)
                _set_cached_md5(file_path, md5sum, file_mtime)

            return cls(
                filepath=file_path,
                ctime=int(getctime(file_path)),
                mtime=file_mtime,
                size=file_size,
                md5sum=md5sum,
                permissions=cls._get_permissions(file_path),
            )
        else:
            return None

    @classmethod
    def from_dict(
        cls,
        data: dict | FileDict,
        dir_prefix: str | None = None,
        strip_dir_prefix: bool = True,
    ) -> "File":
        """Create a File instance from a dictionary."""
        if strip_dir_prefix and not dir_prefix:
            raise ValueError("Set dir_prefix to strip it.")

        data_filepath = data.get("filepath", "")
        if strip_dir_prefix and dir_prefix:
            filepath = str(data_filepath).removeprefix(dir_prefix).lstrip("/")
        elif dir_prefix:
            filepath = join(dir_prefix, str(data_filepath).lstrip("/"))
        else:
            filepath = str(data_filepath)

        return cls(
            filepath=filepath,
            ctime=data.get("ctime"),
            mtime=data.get("mtime"),
            size=data.get("size", 0),
            md5sum=data.get("md5sum"),
            permissions=data.get("permissions"),
        )