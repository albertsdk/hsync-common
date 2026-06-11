"""
File model for HSYNC.

This module defines the File class representing a file with its metadata
(path, timestamps, size, checksum, permissions) used for file synchronization.
"""

from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict

from hsync_common.constants import (
    PARTIAL_DELTA_SUFFIX,
    PARTIAL_DOWNLOAD_SUFFIX,
)
from hsync_common.hashing import adaptive_chunk_size, compute_sha256
from hsync_common.permissions import mode_to_octal
from hsync_common.time_utils import to_epoch

if TYPE_CHECKING:
    # Imported only for type checking to avoid a circular import: version.py
    # imports is_valid_cid from event.py, which imports File from this module.
    from .version import VersionInfo

# =============================================================================
# SHA-256 Cache
# =============================================================================

# Maximum number of entries kept in the SHA-256 LRU cache.
# At ~200 bytes/entry (path + sha256 hex + mtime int) this caps RAM usage at
# roughly 2 MB even on a client with hundreds of thousands of files.
SHA256_CACHE_MAX_SIZE: int = 10_000

# In-memory LRU cache for SHA-256 checksums to avoid redundant computation
# during a single sync operation. Key: filepath, Value: tuple[sha256sum, mtime,
# size]. The size is part of the validity key: on filesystems with coarse mtime
# granularity (1s) a file rewritten in the same second keeps the same mtime, so
# mtime alone would serve a stale digest — the size catches a large class of
# those same-second rewrites.
# OrderedDict is used so we can evict the least-recently-used entry when the
# cache is full (move-to-end on hit, pop-first on overflow).
_sha256_cache: OrderedDict[str, tuple[str, int, int]] = OrderedDict()


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


def _get_cached_sha256(file_path: str, current_mtime: int, current_size: int) -> str | None:
    """Get cached SHA-256 if file metadata still matches (LRU: move to end on hit)."""
    try:
        cached_sha256, cached_mtime, cached_size = _sha256_cache[file_path]
    except KeyError:
        return None
    if cached_mtime == current_mtime and cached_size == current_size:
        _sha256_cache.move_to_end(file_path)
        return cached_sha256
    del _sha256_cache[file_path]
    return None


def _set_cached_sha256(file_path: str, sha256sum: str, mtime: int, size: int) -> None:
    """Store SHA-256 in cache with its mtime/size; evict LRU entry at capacity."""
    _sha256_cache[file_path] = (sha256sum, mtime, size)
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
    # Causal version metadata joined from the version store by producers
    # (server/master listings, events). Optional: absent ⇒ empty clock.
    # Consumers: hsync-server (list JOIN), hsync-client (remote decode),
    # hsync-android (FileInfo.version mirror).
    version: NotRequired["VersionInfo"]


# Parked literal-payload suffix: "<final>.delta.part.lit". Precomputed once
# so the hot is_partial_file() check does not rebuild the string per entry.
_PARTIAL_DELTA_LIT_SUFFIX = f"{PARTIAL_DELTA_SUFFIX}.lit"


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
    # Basename via string ops instead of a Path object (hot: once per scanned
    # entry). Trailing slashes are stripped first so "foo.part/" yields the
    # same basename as Path("foo.part/").name ("foo.part").
    stripped = file_path.rstrip("/")
    sep = stripped.rfind("/")
    name = stripped if sep < 0 else stripped[sep + 1 :]
    return name.endswith(PARTIAL_DOWNLOAD_SUFFIX) or name.endswith(_PARTIAL_DELTA_LIT_SUFFIX)


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
        version: Optional causal version metadata (joined from the store by
            producers; None for files read fresh from disk).
    """

    def __init__(
        self,
        filepath: str | None = None,
        ctime: str | int | float | datetime | None = None,
        mtime: str | int | float | datetime | None = None,
        size: int = 0,
        sha256sum: str | None = None,
        permissions: str | None = None,
        version: "VersionInfo | None" = None,
    ):
        self.filepath = filepath
        # Basename via string ops (hot: one File construction per scanned entry
        # per cycle); trailing slashes are stripped first so "foo/" yields
        # "foo" exactly like Path("foo/").name does.
        if filepath:
            stripped = filepath.rstrip("/")
            sep = stripped.rfind("/")
            self.name = stripped if sep < 0 else stripped[sep + 1 :]
        else:
            self.name = None
        if size < 0:
            raise ValueError(f"File size must be >= 0, got {size}")
        self.size = size
        self.sha256sum = sha256sum
        self.permissions = permissions
        self.version = version
        try:
            self.ctime = self._parse_time(ctime)
            self.mtime = self._parse_time(mtime)
        except (OverflowError, ValueError) as e:
            raise ValueError(f"Invalid timestamp: {e}") from e

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"filepath={self.filepath}, "
            f"name={self.name}, "
            f"ctime={self.ctime}, "
            f"mtime={self.mtime}, "
            f"size={self.size}, "
            f"sha256sum={self.sha256sum}, "
            f"permissions={self.permissions}, "
            f"version={self.version})"
        )

    def _parse_time(self, value: str | int | float | datetime | None) -> int | None:
        """Parse various time formats to Unix timestamp.

        Delegates to :func:`hsync_common.time_utils.to_epoch` — the single
        source of truth for timestamp parsing.  Bools are silently mapped to
        ``None`` (Python ``bool`` is a subclass of ``int``, so ``True``/``False``
        would otherwise parse as epoch 0/1 — a common source of bugs).

        OverflowError and ValueError from malformed or extreme time values
        are allowed to propagate; callers must catch them (the __init__
        constructor wraps them in a ValueError for all init paths).
        """
        try:
            return to_epoch(value)
        except TypeError:
            # bool is not a valid timestamp (rejected by to_epoch).
            return None

    @staticmethod
    def _compute_sha256(filepath: str, file_size: int | None = None) -> str:
        """Compute the SHA-256 checksum of a file with adaptive chunk size."""
        return compute_sha256(filepath, adaptive_chunk_size(file_size))

    def to_dict(self) -> FileDict:
        """Convert the File instance to a FileDict."""
        result = FileDict(
            filepath=self.filepath,
            name=self.name,
            ctime=self.ctime,
            mtime=self.mtime,
            size=self.size,
            sha256sum=self.sha256sum,
            permissions=self.permissions,
        )
        if self.version is not None:
            result["version"] = self.version
        return result

    @classmethod
    def get(cls, file_path: str, buckets_dir: str | None = None) -> "File | None":
        """Get a File instance for an existing file.

        The file can disappear or change concurrently with a sync scan (the
        watcher and transfers share the bucket): any :class:`OSError` raised
        by ``stat``/hash/permission reads degrades to ``None`` instead of
        aborting the whole sync cycle.
        """
        file_path = str(Path(buckets_dir) / file_path.lstrip("/")) if buckets_dir else file_path
        file = Path(file_path)
        try:
            file_stat = file.stat()
        except OSError:
            return None
        file_size = file_stat.st_size
        file_mtime = int(file_stat.st_mtime)

        sha256sum = _get_cached_sha256(file_path, file_mtime, file_size)
        if sha256sum is None:
            try:
                sha256sum = cls._compute_sha256(file_path, file_size)
            except OSError:
                return None
            _set_cached_sha256(file_path, sha256sum, file_mtime, file_size)

        # Reuse the st_mode already read by file.stat() above instead of a
        # second stat syscall (get_permissions would stat the path again).
        permissions = mode_to_octal(file_stat.st_mode)

        return cls(
            filepath=file_path,
            ctime=int(file_stat.st_ctime),
            mtime=file_mtime,
            size=file_size,
            sha256sum=sha256sum,
            permissions=permissions,
        )

    @classmethod
    def from_dict(
        cls,
        data: dict | FileDict,
        dir_prefix: str | None = None,
        strip_dir_prefix: bool = True,
    ) -> "File":
        """Create a File instance from a dictionary."""
        from hsync_common.models import _resolve_prefixed_path

        filepath = _resolve_prefixed_path(
            data.get("filepath", ""), dir_prefix, strip=strip_dir_prefix
        )

        return cls(
            filepath=filepath,
            ctime=data.get("ctime"),
            mtime=data.get("mtime"),
            size=data.get("size", 0),
            sha256sum=data.get("sha256sum"),
            permissions=data.get("permissions"),
            version=data.get("version"),
        )
