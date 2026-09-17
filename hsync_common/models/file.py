"""
File model for HSYNC.

This module defines the File class representing a file with its metadata
(path, timestamps, size, checksum, permissions) used for file synchronization.
"""

import os
from collections import OrderedDict
from datetime import datetime
from threading import Lock
from typing import TYPE_CHECKING, NotRequired, TypedDict

from hsync_common.constants import (
    PARTIAL_DELTA_SUFFIX,
    PARTIAL_DOWNLOAD_SUFFIX,
)
from hsync_common.hashing import compute_sha256
from hsync_common.path_validation import basename
from hsync_common.permissions import mode_to_octal
from hsync_common.time_utils import to_epoch

from ._util import _resolve_prefixed_path

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
# across sync cycles. Key: filepath, Value: tuple[sha256sum, mtime_ns,
# ctime_ns, size]. The identity is validated at nanosecond granularity on
# every hit: ctime changes on ANY write (content or metadata) with the
# kernel's finest resolution, so a rewrite that preserves mtime and size —
# e.g. a same-second same-size rewrite on a coarse-mtime filesystem, or a
# ``touch -r``-style mtime restoration — still evicts the stale digest.
# Callers additionally invalidate single entries on observed mutations
# (watcher events, post-download/post-upload writes).
# OrderedDict is used so we can evict the least-recently-used entry when the
# cache is full (move-to-end on hit, pop-first on overflow).
_sha256_cache: OrderedDict[str, tuple[str, int, int, int]] = OrderedDict()

# Guards every access to ``_sha256_cache``. Readers are multi-threaded by
# design: hsync-client reads metadata from scan/transfer pool threads and
# hsync-server offloads listing metadata (hash-on-miss) to asyncio worker
# threads, so the LRU's check-then-act sequences (hit check + move-to-end,
# stale drop, overflow eviction) must never interleave.
_sha256_cache_lock = Lock()


def clear_sha256_cache() -> None:
    """Clear the entire SHA-256 cache.

    Called at the start of each sync cycle in one-shot mode (no live
    watcher invalidating entries) to guarantee fresh checksums. Continuous
    mode relies on per-entry invalidation plus the nanosecond identity
    check instead, so unchanged files are never re-hashed.
    """
    with _sha256_cache_lock:
        _sha256_cache.clear()


def invalidate_sha256_cache(file_path: str) -> None:
    """Remove a single entry from the SHA-256 cache.

    Should be called when a file is known to have been modified
    (e.g. after a download, upload, or watchdog event) so that
    the next ``File.get()`` recomputes the checksum.

    Args:
        file_path: Path of the file to invalidate.
    """
    with _sha256_cache_lock:
        _sha256_cache.pop(file_path, None)


def _get_cached_sha256(
    file_path: str, current_mtime_ns: int, current_ctime_ns: int, current_size: int
) -> str | None:
    """Get cached SHA-256 if file metadata still matches (LRU: move to end on hit)."""
    with _sha256_cache_lock:
        try:
            cached_sha256, cached_mtime_ns, cached_ctime_ns, cached_size = _sha256_cache[file_path]
        except KeyError:
            return None
        if (
            cached_mtime_ns == current_mtime_ns
            and cached_ctime_ns == current_ctime_ns
            and cached_size == current_size
        ):
            _sha256_cache.move_to_end(file_path)
            return cached_sha256
        _sha256_cache.pop(file_path, None)
        return None


def _set_cached_sha256(
    file_path: str, sha256sum: str, mtime_ns: int, ctime_ns: int, size: int
) -> None:
    """Store SHA-256 in cache with its stat identity; evict LRU entry at capacity."""
    with _sha256_cache_lock:
        _sha256_cache[file_path] = (sha256sum, mtime_ns, ctime_ns, size)
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
    name = basename(file_path)
    return name.endswith(PARTIAL_DOWNLOAD_SUFFIX) or name.endswith(_PARTIAL_DELTA_LIT_SUFFIX)


def is_hidden_file(file_path: str) -> bool:
    """Return True when *file_path* must be excluded from synchronisation.

    See :func:`hsync_common.ignore.should_skip` for the filtering rules
    (active IgnoreMatcher, then built-in default patterns).
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
        self.name = basename(filepath) if filepath else None
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
        file_path = _resolve_prefixed_path(file_path, buckets_dir, strip=False)
        try:
            file_stat = os.stat(file_path)
        except OSError:
            return None
        file_size = file_stat.st_size
        file_mtime = int(file_stat.st_mtime)
        file_mtime_ns = int(file_stat.st_mtime_ns)
        file_ctime_ns = int(file_stat.st_ctime_ns)

        sha256sum = _get_cached_sha256(file_path, file_mtime_ns, file_ctime_ns, file_size)
        if sha256sum is None:
            try:
                sha256sum = compute_sha256(file_path)
            except OSError:
                return None
            _set_cached_sha256(file_path, sha256sum, file_mtime_ns, file_ctime_ns, file_size)

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
        """Create a File instance from a dictionary.

        Fast path: the production wire shape (``to_dict`` / server listing)
        always emits ``filepath``, ``ctime``, ``mtime``, ``size``,
        ``sha256sum`` and ``permissions``, so the common case resolves every
        key with ``data[...]`` lookups (no ``dict.get`` default machinery):
        ~1.4x faster than ``get`` on a full dict. Partial dicts (hand-built
        test payloads with only a subset of keys) fall back to ``get``-based
        decode so ``KeyError`` is never raised on a legitimately optional
        field. The construction is shared by both paths: only the lookup
        strategy (and the ``size`` default) differ.
        """
        required = ("filepath", "ctime", "mtime", "size", "sha256sum", "permissions")
        fast = all(key in data for key in required)
        lookup = data.__getitem__ if fast else data.get
        filepath = _resolve_prefixed_path(
            str(data.get("filepath") or ""),
            dir_prefix,
            strip=strip_dir_prefix,
        )
        return cls(
            filepath=filepath,
            ctime=lookup("ctime"),
            mtime=lookup("mtime"),
            size=data["size"] if fast else data.get("size", 0),
            sha256sum=lookup("sha256sum"),
            permissions=lookup("permissions"),
            version=data.get("version"),
        )
