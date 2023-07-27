"""
File model for HSYNC.

This module defines the File class representing a file with its metadata
(path, timestamps, size, checksum, permissions) used for file synchronization.
"""

import stat
from collections import OrderedDict
from datetime import UTC, datetime
from hashlib import sha256
from os import stat as os_stat
from pathlib import Path
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
# SHA-256 Cache
# =============================================================================

# Maximum number of entries kept in the SHA-256 LRU cache.
# At ~200 bytes/entry (path + sha256 hex + mtime int) this caps RAM usage at
# roughly 2 MB even on a client with hundreds of thousands of files.
SHA256_CACHE_MAX_SIZE: int = 10_000

# In-memory LRU cache for SHA-256 checksums to avoid redundant computation
# during a single sync operation. Key: filepath, Value: tuple[sha256sum, mtime].
# OrderedDict is used so we can evict the least-recently-used entry when the
# cache is full (move-to-end on hit, pop-first on overflow).
_sha256_cache: OrderedDict[str, tuple[str, int]] = OrderedDict()


def clear_sha256_cache() -> None:
    """Clear the entire SHA-256 cache.

    Should be called at the start of each sync cycle to ensure
    fresh checksums are computed for all files.
    """
    _sha256_cache.clear()


def invalidate_sha256_cache(file_path: str) -> None:
    """Remove a single entry from the SHA-256 cache.

    Should be called when a file is known to have been modified
    (e.g. after a download, upload, or watchdog event) so that
    the next ``File.get()`` recomputes the checksum.

    Args:
        file_path: Path of the file to invalidate.
    """
    _sha256_cache.pop(file_path, None)


def _get_cached_sha256(file_path: str, current_mtime: int) -> str | None:
    """Get cached SHA-256 if file hasn't been modified (LRU: move to end on hit)."""
    if file_path in _sha256_cache:
        cached_sha256, cached_mtime = _sha256_cache[file_path]
        if cached_mtime == current_mtime:
            _sha256_cache.move_to_end(file_path)
            return cached_sha256
        del _sha256_cache[file_path]
    return None


def _set_cached_sha256(file_path: str, sha256sum: str, mtime: int) -> None:
    """Store SHA-256 in cache with its mtime; evict LRU entry when at capacity."""
    _sha256_cache[file_path] = (sha256sum, mtime)
    _sha256_cache.move_to_end(file_path)
    if len(_sha256_cache) > SHA256_CACHE_MAX_SIZE:
        _sha256_cache.popitem(last=False)  # evict oldest (least recently used)


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
    sha256sum: str | None
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
    name = Path(file_path).name

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
        sha256sum: SHA-256 checksum of file content.
        permissions: Symbolic permission string (e.g., '-rw-r--r--').
    """

    def __init__(
        self,
        filepath: str | None = None,
        ctime: str | int | float | datetime | None = None,
        mtime: str | int | float | datetime | None = None,
        size: int = 0,
        sha256sum: str | None = None,
        permissions: str | None = None,
    ):
        self.filepath = filepath
        self.name = Path(filepath).name if filepath else None
        self.size = size
        self.sha256sum = sha256sum
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
            f"sha256sum={self.sha256sum}, "
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
    def _compute_sha256(filepath: str, file_size: int | None = None) -> str:
        """Compute the SHA-256 checksum of a file with adaptive chunk size."""
        if file_size is not None:
            if file_size >= FILE_SIZE_MEDIUM:
                chunk_size = CHUNK_SIZE_LARGE
            elif file_size >= FILE_SIZE_SMALL:
                chunk_size = CHUNK_SIZE_MEDIUM
            else:
                chunk_size = CHUNK_SIZE_SMALL
        else:
            chunk_size = CHUNK_SIZE_SMALL

        hash_sha256 = sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

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
            sha256sum=self.sha256sum,
            permissions=self.permissions,
        )

    @classmethod
    def get(cls, file_path: str, buckets_dir: str | None = None) -> Optional["File"]:
        """Get a File instance for an existing file."""
        file_path = str(Path(buckets_dir) / file_path.lstrip("/")) if buckets_dir else file_path
        file = Path(file_path)
        if file.exists():
            file_stat = file.stat()
            file_size = file_stat.st_size
            file_mtime = int(file_stat.st_mtime)

            sha256sum = _get_cached_sha256(file_path, file_mtime)
            if sha256sum is None:
                sha256sum = cls._compute_sha256(file_path, file_size)
                _set_cached_sha256(file_path, sha256sum, file_mtime)

            return cls(
                filepath=file_path,
                ctime=int(file_stat.st_ctime),
                mtime=file_mtime,
                size=file_size,
                sha256sum=sha256sum,
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
            filepath = str(Path(dir_prefix) / str(data_filepath).lstrip("/"))
        else:
            filepath = str(data_filepath)

        return cls(
            filepath=filepath,
            ctime=data.get("ctime"),
            mtime=data.get("mtime"),
            size=data.get("size", 0),
            sha256sum=data.get("sha256sum"),
            permissions=data.get("permissions"),
        )
