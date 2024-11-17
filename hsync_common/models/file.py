"""
File model for HSYNC.

This module defines the File class representing a file with its metadata
(path, timestamps, size, checksum, permissions) used for file synchronization.
"""

from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional, TypedDict

from hsync_common.constants import (
    PARTIAL_DELTA_SUFFIX,
    PARTIAL_DOWNLOAD_SUFFIX,
)
from hsync_common.hashing import adaptive_chunk_size, compute_sha256
from hsync_common.permissions import get_permissions

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


def is_partial_file(file_path: str) -> bool:
    """Return True if *file_path* is an in-progress hsync transfer artifact.

    Bytes are streamed to ``<final>.part`` and atomically renamed to the final
    name only after the SHA-256 checksum is verified, so a ``.part`` file is
    always a transient internal artifact that must be excluded from
    synchronisation regardless of
    ``.hsyncignore`` rules. The same applies to delta-transfer artifacts:
    ``<final>.delta.part`` (already covered by the ``.part`` suffix) and the
    parked literal payload ``<final>.delta.part.lit``.

    Args:
        file_path: Path (or bare filename) to check.

    Returns:
        True if the basename ends with a partial-transfer suffix.
    """
    name = Path(file_path).name
    return name.endswith(PARTIAL_DOWNLOAD_SUFFIX) or name.endswith(f"{PARTIAL_DELTA_SUFFIX}.lit")


def is_hidden_file(file_path: str) -> bool:
    """
    Check if a file must be excluded from synchronisation.

    When a process-wide :class:`hsync_common.ignore.IgnoreMatcher` is active
    (installed by the client at startup) it is consulted so that
    ``.hsyncignore`` rules and extra patterns are honoured. When no matcher
    is installed (e.g. on the server) the built-in default ignore patterns
    (:data:`hsync_common.constants.DEFAULT_IGNORE_PATTERNS`) are used.

    Following the industry standard (Syncthing, rsync, Nextcloud, OneDrive),
    dotfiles in general (``.env``, ``.config`` …) are **not** excluded: only
    OS cache files and editor/office temporary files are filtered by default.

    Args:
        file_path: Path to the file to check.

    Returns:
        True if the file is ignored, False otherwise.
    """
    from hsync_common.ignore import should_skip

    return should_skip(file_path, is_dir=False)


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
        permissions: Octal permission string (e.g., '644').
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
        return compute_sha256(filepath, adaptive_chunk_size(file_size))

    @staticmethod
    def _get_permissions(obj_path: str) -> str:
        """Get file permissions as a canonical octal string."""
        return get_permissions(obj_path)

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
