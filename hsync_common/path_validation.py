# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Path and filename validation utilities shared across HSYNC projects.

This module provides cross-platform validation for filenames and paths,
ensuring compatibility with Windows, Linux, and macOS file systems.

Based on Microsoft documentation:
https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file
"""

import os
import re
import unicodedata
from pathlib import Path

from hsync_common.constants import (
    HSYNCFOLDER_FILENAME,
    HSYNCIGNORE_FILENAME,
    HSYNCSTATE_FILENAME,
    HSYNCTOMBSTONES_FILENAME,
    PARTIAL_DOWNLOAD_SUFFIX,
)

# =============================================================================
# Forbidden Characters
# =============================================================================

# Forbidden characters in filenames (cross-platform)
# Windows: < > : " / \ | ? * and characters 0-31
# Linux/macOS: / and NUL (\x00)
# For cross-platform compatibility, we use the union of all restrictions.
FORBIDDEN_FILENAME_CHARS: frozenset[str] = frozenset(
    {
        "<",
        ">",
        ":",
        '"',
        "/",
        "\\",
        "|",
        "?",
        "*",
        "\x00",  # NUL - forbidden on all systems
    }
)

# Control characters (ASCII 1-31) - forbidden on Windows
# These are checked separately for efficiency
CONTROL_CHARS: frozenset[str] = frozenset(chr(i) for i in range(1, 32))

# Forbidden characters in path parts (allows / for path separator).
# Derived from FORBIDDEN_FILENAME_CHARS minus the forward slash.
FORBIDDEN_PATH_CHARS: frozenset[str] = FORBIDDEN_FILENAME_CHARS - {"/"}

# Single merged set for the wire-relpath scan: one C-level ``isdisjoint`` pass
# instead of two (forbidden + control), precomputed so the union is never rebuilt.
_FORBIDDEN_OR_CONTROL: frozenset[str] = FORBIDDEN_PATH_CHARS | CONTROL_CHARS

# =============================================================================
# Reserved Filenames
# =============================================================================

# Reserved filenames (Windows compatibility)
# These names are reserved in every directory and cannot be used as filenames.
# Also reserved when followed by an extension (e.g., NUL.txt, COM1.log)
#
# Note: Windows also recognizes superscript digits ¹²³ (ISO 8859-1) as valid
# parts of COM# and LPT# device names (e.g., COM¹ is reserved).
RESERVED_FILENAMES: frozenset[str] = frozenset(
    {
        # Standard device names
        "CON",
        "PRN",
        "AUX",
        "NUL",
        # Serial ports COM1-COM9 and superscript variants
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "COM\u00b9",
        "COM\u00b2",
        "COM\u00b3",  # COM¹, COM², COM³
        # Parallel ports LPT1-LPT9 and superscript variants
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
        "LPT\u00b9",
        "LPT\u00b2",
        "LPT\u00b3",  # LPT¹, LPT², LPT³
    }
)

# Characters that are problematic at the end of filenames (Windows)
# Windows shell ignores trailing spaces and periods
PROBLEMATIC_TRAILING_CHARS: frozenset[str] = frozenset({" ", "."})

# A whole ".." path component (between / separators or at either end).
_DOTDOT_COMPONENT_RE = re.compile(r"(?:^|/)\.\.(?:/|$)")

# One-pass C-level replacement of every forbidden/control char with "_".
_SANITIZE_TABLE = str.maketrans({ord(c): "_" for c in FORBIDDEN_FILENAME_CHARS | CONTROL_CHARS})


# =============================================================================
# Validation Functions
# =============================================================================


def basename(path: str) -> str:
    """Return the last path component without allocating a :class:`Path`.

    Trailing slashes are stripped first so ``"foo/"`` yields ``"foo"``,
    matching :attr:`pathlib.Path.name`. Empty / slash-only input yields ``""``.

    Consumers: ``hsync-common`` (``File``, ``is_partial_file``,
    ``IgnoreMatcher.matches``) — hot path, once per scanned entry.
    """
    stripped = path.rstrip("/")
    if not stripped:
        return ""
    sep = stripped.rfind("/")
    return stripped if sep < 0 else stripped[sep + 1 :]


def has_forbidden_chars(name: str, chars: frozenset[str]) -> bool:
    """Check if name contains any forbidden characters.

    ``set.isdisjoint`` walks *name* once with O(1) hash lookups instead of
    rescanning the whole name for every forbidden char (O(n·m) → O(n)).
    """
    return not chars.isdisjoint(name)


def has_control_chars(name: str) -> bool:
    """Check if name contains any control characters (ASCII 1-31)."""
    return not CONTROL_CHARS.isdisjoint(name)


def is_reserved_name(name: str) -> bool:
    """
    Check if name is a Windows reserved filename.

    Handles names with or without extensions (e.g., NUL.txt is also reserved).
    """
    # Get base name without extension for checking reserved names.
    # split(".", 1) stops at the first separator: same base name as
    # split(".")[0] (or the name itself when there is no dot) without
    # building the full component list.
    base_name = name.split(".", 1)[0].upper()
    return base_name in RESERVED_FILENAMES


def has_problematic_trailing(name: str) -> bool:
    """Check if name ends with problematic characters (space or period)."""
    return bool(name) and name[-1] in PROBLEMATIC_TRAILING_CHARS


def is_valid_filename(filename: str) -> bool:
    """
    Validate a filename for cross-platform compatibility.

    Checks for:
    - Empty filename
    - Forbidden characters (cross-platform)
    - Control characters (ASCII 1-31)
    - Reserved names on Windows (including with extensions, e.g., NUL.txt)
    - Problematic trailing characters (space, period)
    - Path traversal attempts (../ or ..\\)
    - Absolute paths

    Args:
        filename: The filename to validate (without path).

    Returns:
        True if the filename is valid, False otherwise.
    """
    if not filename:
        return False

    if has_forbidden_chars(filename, FORBIDDEN_FILENAME_CHARS):
        return False

    if has_control_chars(filename):
        return False

    if is_reserved_name(filename):
        return False

    if has_problematic_trailing(filename):
        return False

    # Separators/drive-letters/emptiness are already rejected by the guards
    # above (FORBIDDEN_FILENAME_CHARS covers ``/``, ``\\`` and ``:``), so the
    # only remaining traversal risk is a ``..`` component.
    return not has_dotdot_component(filename)


def has_dotdot_component(path: str) -> bool:
    """
    Check if a path contains ".." as a whole path component.

    This detects parent directory traversal (e.g. ``../secret``,
    ``foo/../../bar``, mixed ``foo/..\\bar``) while still allowing filenames
    that merely embed two dots in the name (e.g. ``lib..1.dylib``,
    ``a..b.txt``, ``v1.2.3.tar.gz``).

    Args:
        path: The path to inspect.

    Returns:
        True if any component (split on / or \\) is exactly "..".
    """
    # Normalize separators, then look for an exact ".." component with a
    # single C-regex pass (no intermediate split list allocation). The replace
    # is skipped on POSIX-style paths with no backslash (the dominant case).
    if "\\" in path:
        path = path.replace("\\", "/")
    return bool(_DOTDOT_COMPONENT_RE.search(path))


def is_safe_path_component(path: str) -> bool:
    """
    Check if a path component is safe (no path traversal or absolute paths).

    This function prevents path traversal attacks by ensuring the path:
    - Does not contain ".." as a path component (parent directory references)
    - Is not an absolute path (doesn't start with / or drive letter)
    - Doesn't contain Windows drive letter references (C:, D:, etc.)

    Filenames that merely embed two dots (e.g. ``lib..1.dylib``) are allowed.

    Args:
        path: The path component to validate.

    Returns:
        True if the path is safe, False otherwise.
    """
    if not path:
        return False

    # Check for absolute paths
    if path.startswith(("/", "\\")):
        return False

    # Check for Windows drive letters (C:, D:, etc.)
    if len(path) >= 2 and path[1] == ":":
        return False

    # Reject parent directory traversal (".." as a component, not substring)
    return not has_dotdot_component(path)


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing/replacing dangerous characters.

    This function:
    - Removes path separators
    - Replaces forbidden characters with underscores
    - Removes control characters
    - Strips problematic trailing characters
    - Truncates to safe length (255 chars)

    Args:
        filename: The filename to sanitize.

    Returns:
        A sanitized filename safe for storage.
    """
    if not filename:
        return "unnamed"

    # Remove path separators - extract just the filename
    if "/" in filename:
        filename = filename.rsplit("/", 1)[-1]
    if "\\" in filename:
        filename = filename.rsplit("\\", 1)[-1]

    # Remove or replace forbidden characters (single C-level translate pass;
    # every forbidden/control char maps to "_", identical to the old loop).
    filename = filename.translate(_SANITIZE_TABLE)

    # Remove problematic trailing characters
    filename = filename.rstrip(" .")

    # Truncate to maximum filename length (255 bytes is the typical limit on
    # most filesystems). Truncation is byte-aware so a multi-byte UTF-8
    # sequence is never split in the middle (which would produce an invalid
    # encoding). The extension is preserved when possible.
    filename_bytes = filename.encode("utf-8")
    if len(filename_bytes) > 255:
        name, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
        ext_bytes = ext.encode("utf-8")
        # Reserve 1 byte for the dot + ext bytes; truncate the name part.
        max_name_bytes = 255 - len(ext_bytes) - 1 if ext else 255
        # Truncate the name to max_name_bytes without splitting a UTF-8
        # character: decode with errors="ignore" drops any partial trailing
        # sequence.
        name_truncated = name.encode("utf-8")[:max_name_bytes].decode("utf-8", errors="ignore")
        filename = f"{name_truncated}.{ext}" if ext else name_truncated

    # Handle empty or reserved names. ``is_reserved_name`` correctly handles
    # names with extensions (e.g. "NUL.txt" is reserved), unlike a plain
    # ``filename.upper() in RESERVED_FILENAMES`` check.
    if not filename or is_reserved_name(filename):
        filename = "unnamed"

    return filename


# =============================================================================
# Bucket Name Validation
# =============================================================================

# Canonical bucket-name pattern shared by client, server and desktop.
# Bucket names must be alphanumeric, may contain hyphens and underscores in
# the middle, but cannot start or end with a hyphen or underscore.
BUCKET_NAME_PATTERN = r"^[a-zA-Z0-9]([a-zA-Z0-9_-]*[a-zA-Z0-9])?$"

# Maximum bucket name length.  The bucket name becomes a directory entry on the
# server and a local folder name on the client; filesystems typically limit
# individual path components to 255 bytes (Linux ext4, macOS APFS, Windows NTFS).
# A generous 63-character limit keeps the name human-readable and leaves ample
# room for the prefixed path components that the server / client construct around
# it (``<buckets_path>/<bucket>/…``), well within the 255-byte component cap
# even when the name is pure ASCII but the path prefix uses multi-byte UTF-8.
MAX_BUCKET_NAME_LENGTH = 63

_BUCKET_NAME_RE = re.compile(BUCKET_NAME_PATTERN)


def is_valid_bucket_name(value: str) -> bool:
    """Validate a bucket name against the canonical HSYNC pattern.

    Bucket names must contain only alphanumeric characters, hyphens and
    underscores, and cannot start or end with a hyphen or underscore.
    The length must not exceed ``MAX_BUCKET_NAME_LENGTH`` (63 characters).

    Args:
        value: The bucket name to validate.

    Returns:
        True if the bucket name is valid, False otherwise.
    """
    if not value or not isinstance(value, str):
        return False
    if len(value) > MAX_BUCKET_NAME_LENGTH:
        return False
    return bool(_BUCKET_NAME_RE.match(value))


# =============================================================================
# Safe Path Resolution
# =============================================================================


def safe_resolve_path(path: str, *, allow_absolute: bool = True) -> str | None:
    """Resolve a filesystem path, rejecting traversal and unsafe inputs.

    The path is stripped of NUL bytes, checked for ``..`` traversal
    components and resolved with :meth:`pathlib.Path.resolve`. When
    ``allow_absolute`` is False, resolved absolute paths are rejected.

    Args:
        path: The path to validate and resolve.
        allow_absolute: If False, only relative paths are accepted.

    Returns:
        The resolved path as a string if safe, or ``None`` otherwise.
    """
    if not path:
        return None

    # Strip NUL bytes which are never valid in paths.
    path = path.replace("\x00", "")

    # Reject parent-directory traversal as a whole component.
    if has_dotdot_component(path):
        return None

    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError):
        return None

    if not allow_absolute and resolved.is_absolute():
        return None

    return str(resolved)


# =============================================================================
# Wire-facing Remote Path Validation
# =============================================================================
#
# The helpers below are the single point of truth for validating paths that
# arrive from a remote peer (server, LAN master or LAN slave) inside events,
# listings or transfer requests. They MUST be applied before any local
# filesystem operation is derived from a remote-supplied path.

# Filenames owned by the sync engine itself. They live inside the synced
# bucket but must NEVER be accepted from the wire: a remote peer that could
# (re)write them would alter the victim's sync behaviour (ignore rules,
# folder identity, leftover legacy side-cars) using the sync channel itself.
# ``.hsyncstate`` / ``.hsynctombstones`` are no longer written (ADR-0025) but
# stay rejected so an old peer cannot plant them.
INTERNAL_FILENAMES: frozenset[str] = frozenset(
    {
        HSYNCIGNORE_FILENAME,
        HSYNCFOLDER_FILENAME,
        HSYNCSTATE_FILENAME,
        HSYNCTOMBSTONES_FILENAME,
    }
)

# Lowercase view of :data:`INTERNAL_FILENAMES` for the case-insensitive
# matching done by :func:`is_internal_name` (case-insensitive filesystems).
_INTERNAL_FILENAMES_LOWER: frozenset[str] = frozenset(n.lower() for n in INTERNAL_FILENAMES)

# Lowercase partial-download suffix, precomputed so the hot is_internal_name()
# check does not rebuild it per scanned entry.
_PARTIAL_SUFFIX_LOWER: str = PARTIAL_DOWNLOAD_SUFFIX.lower()


def is_internal_name(name: str) -> bool:
    """Return True if *name* is an internal sync-engine artifact.

    Matches the basename against :data:`INTERNAL_FILENAMES` and the partial
    download suffix (``.part``). The per-peer sentinel ``.hsynckeep`` is NOT
    internal: it legitimately appears in delete events handled by clients.

    The comparison is case-insensitive: on case-insensitive filesystems
    (Windows, default macOS) ``.HSYNCIGNORE`` and ``.hsyncignore`` are the
    same file, so a case-variant must be rejected too — otherwise a remote
    peer could overwrite the victim's engine artifacts through the wire.

    Args:
        name: A filename or path; only the basename is considered.

    Returns:
        True when the basename is an engine-owned artifact.
    """
    if "/" in name or "\\" in name:
        base = name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
    else:
        # Fast path: an already-basename value (the common caller shape) skips
        # the separator folding / trailing-strip / split entirely.
        base = name.lower()
    return base in _INTERNAL_FILENAMES_LOWER or base.endswith(_PARTIAL_SUFFIX_LOWER)


# Path-carrying keys of a sync event payload (both may be present at once —
# e.g. a payload crafted with a valid ``filepath`` and a malicious ``path``).
# Single source of truth for every inbound event gate (server relay, client
# dispatch), so the key set can never drift between peers.
WIRE_PATH_KEYS = ("filepath", "path")


def wire_relpaths(payload: dict) -> list[str]:
    """Return every bucket-relative path carried by an event payload.

    Both ``filepath`` and ``path`` may be present at once: validating only the
    first would let a payload smuggle a malicious second key past the gate, so
    every present key must be validated by the caller.
    """
    paths = []
    for key in WIRE_PATH_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    return paths


# Maximum byte length of a single path component (filename). Most filesystems
# (ext4, XFS, NTFS, APFS) enforce a 255-byte limit per component.
MAX_PATH_COMPONENT_BYTES = 255

# Maximum total byte length of a bucket-relative path. 4096 is the Linux
# PATH_MAX; keeping the wire path well below it leaves room for the bucket
# root prefix on the receiving peer and avoids ENAMETOOLONG at every cycle.
MAX_REMOTE_RELPATH_BYTES = 4096


def validate_remote_relpath(rel: str) -> str | None:
    """Validate a bucket-relative path received from a remote peer.

    Rejects (returns ``None`` for):
    - empty/non-string input, ``.`` and ``..`` components, absolute paths
      and Windows drive letters;
    - backslashes and any cross-platform forbidden/control characters
      (protects Windows peers from Linux-legal but hostile names);
    - Windows reserved names and problematic trailing characters in any
      path component;
    - path components longer than 255 bytes or total path longer than
      4096 bytes (avoids ENAMETOOLONG and hostile multi-MB paths);
    - internal sync-engine artifacts (see :data:`INTERNAL_FILENAMES`).

    Args:
        rel: The bucket-relative path to validate.

    Returns:
        The normalized relative path (leading/trailing slashes stripped)
        when safe, ``None`` otherwise.
    """
    if not rel or not isinstance(rel, str):
        return None

    # Normalize Unicode to NFC so homoglyph attacks (e.g. U+2024 ‥ as "..",
    # fullwidth U+FF0F as "/") cannot bypass the component-level checks
    # below. Normalize BEFORE every subsequent guard so the normalized form
    # is what the filesystem eventually sees.
    if not unicodedata.is_normalized("NFC", rel):
        rel = unicodedata.normalize("NFC", rel)

    # Absolute paths and drive letters are never acceptable on the wire.
    if not is_safe_path_component(rel):
        return None

    # Backslash and other cross-platform forbidden/control characters: one
    # merged C-level scan instead of two (forbidden then control).
    if not _FORBIDDEN_OR_CONTROL.isdisjoint(rel):
        return None

    rel = rel.strip("/")
    if not rel:
        return None

    # Total path length bound (byte-aware for cross-platform safety).
    total_bytes = len(rel.encode("utf-8"))
    if total_bytes > MAX_REMOTE_RELPATH_BYTES:
        return None
    # A component can never exceed 255 bytes when the whole path already fits
    # in 255 bytes, so the per-component byte check below is skipped for the
    # common short-path case.
    check_component_bytes = total_bytes > MAX_PATH_COMPONENT_BYTES

    for part in rel.split("/"):
        if not part or part in (".", ".."):
            return None
        if is_reserved_name(part) or has_problematic_trailing(part):
            return None
        # Per-component byte bound (filesystem limit).
        if check_component_bytes and len(part.encode("utf-8")) > MAX_PATH_COMPONENT_BYTES:
            return None

    if is_internal_name(rel):
        return None

    return rel


def resolve_within(base_dir: str, rel: str, *, resolve_final: bool = True) -> str | None:
    """Resolve a remote-supplied relative path inside *base_dir*.

    Combines lexical validation (:func:`validate_remote_relpath`) with
    filesystem confinement: the resolved path must remain within
    ``base_dir`` even after symlink resolution of existing components.

    When *resolve_final* is False the **final component is not
    dereferenced**: a symlink at the endpoint is returned as the link path.
    This is required by every operation that must treat a symlink
    structurally (delete the link itself, replace an existing link) instead
    of acting on its target — while intermediate directory symlinks remain
    resolved and confined, so an escaping hop is still rejected.

    Args:
        base_dir: The directory the path must stay within (e.g. the local
            bucket root).
        rel: The remote-supplied bucket-relative path.
        resolve_final: When True (default) the returned path is fully
            resolved — the safe choice for file/directory content paths.

    Returns:
        The confined absolute path, or ``None`` when the path is unsafe.
    """
    clean = validate_remote_relpath(rel)
    if clean is None:
        return None

    try:
        base = Path(base_dir).resolve()
        if resolve_final:
            target = (base / clean).resolve()
        else:
            target = (base / Path(clean).parent).resolve() / Path(clean).name
        target.relative_to(base)
    except (OSError, ValueError):
        return None

    return str(target)


def _resolve_target_in_bucket(symlink_path: str, target: str, bucket_dir: str) -> Path | None:
    """Resolve a symlink *target* and return it when it stays inside *bucket_dir*.

    Absolute targets are resolved as-is; relative targets are resolved from the
    link's parent directory. ``None`` signals an unresolvable input (e.g. an
    embedded NUL byte or an over-long component) or a target that escapes the
    bucket. Single source of truth for the confinement check shared by
    :func:`wire_symlink_target` and :func:`is_safe_symlink_target`.
    """
    if not target:
        return None
    try:
        bucket_path = Path(bucket_dir).resolve()
        if Path(target).is_absolute():
            resolved = Path(target).resolve()
        else:
            resolved = (Path(symlink_path).parent / target).resolve()
        resolved.relative_to(bucket_path)
    except (OSError, ValueError):
        return None
    return resolved


def wire_symlink_target(symlink_path: str, target: str, bucket_dir: str) -> str | None:
    """Normalize a symlink target for wire replication (rsync munge semantics).

    The (path, target) pair is replicated structurally, but an ABSOLUTE target
    is not portable: it refers to the sender's filesystem layout and would
    dangle (or be rejected) on every other peer. An absolute target that
    resolves inside *bucket_dir* is therefore converted to a path RELATIVE to
    the link's own directory, preserving the reference it denotes while making
    it valid on any peer regardless of where the bucket is mounted. A relative
    target is returned verbatim. Returns ``None`` when the absolute target
    resolves outside the bucket (the caller must skip the link entirely).

    Args:
        symlink_path: Full path where the symlink lives.
        target: The symlink target (relative or absolute).
        bucket_dir: The bucket directory.

    Returns:
        The wire-safe target string, or ``None`` when escaping the bucket.
    """
    if not target:
        return None
    if not Path(target).is_absolute():
        return target
    resolved = _resolve_target_in_bucket(symlink_path, target, bucket_dir)
    if resolved is None:
        return None
    try:
        link_parent = Path(symlink_path).resolve().parent
        return os.path.relpath(resolved, link_parent)
    except (OSError, ValueError):
        return None


def is_safe_symlink_target(symlink_path: str, target: str, bucket_dir: str) -> bool:
    """Validate that a symlink target stays within the bucket directory.

    Absolute targets must resolve inside *bucket_dir*; relative targets are
    resolved from the symlink's parent directory.

    Args:
        symlink_path: Full path where the symlink will be created.
        target: The target path the symlink will point to.
        bucket_dir: The bucket directory that must contain the target.

    Returns:
        True if the resolved target is within the bucket, False otherwise.
    """
    return _resolve_target_in_bucket(symlink_path, target, bucket_dir) is not None
