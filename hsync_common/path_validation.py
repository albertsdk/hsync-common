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

import re

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

# Forbidden characters in path parts (allows / for path separator)
# Same as FORBIDDEN_FILENAME_CHARS but without forward slash
FORBIDDEN_PATH_CHARS: frozenset[str] = frozenset(
    {
        "<",
        ">",
        ":",
        '"',
        "\\",
        "|",
        "?",
        "*",
        "\x00",  # NUL - forbidden on all systems
    }
)

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


# =============================================================================
# Validation Functions
# =============================================================================


def has_forbidden_chars(name: str, chars: frozenset[str]) -> bool:
    """Check if name contains any forbidden characters."""
    return any(char in name for char in chars)


def has_control_chars(name: str) -> bool:
    """Check if name contains any control characters (ASCII 1-31)."""
    return any(char in name for char in CONTROL_CHARS)


def is_reserved_name(name: str) -> bool:
    """
    Check if name is a Windows reserved filename.

    Handles names with or without extensions (e.g., NUL.txt is also reserved).
    """
    # Get base name without extension for checking reserved names
    base_name = name.split(".")[0].upper() if "." in name else name.upper()
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

    return is_safe_path_component(filename)


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
    # Normalize separators, then split and look for an exact ".." component
    return ".." in path.replace("\\", "/").split("/")


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
    if path.startswith("/") or path.startswith("\\"):
        return False

    # Check for Windows drive letters (C:, D:, etc.)
    if len(path) >= 2 and path[1] == ":":
        return False

    # Reject parent directory traversal (".." as a component, not substring)
    return not has_dotdot_component(path)


def is_valid_path(path: str, base_dir: str) -> bool:
    """
    Validate a full path against a base directory to prevent path traversal.

    This function ensures the resolved path stays within the base directory,
    preventing attacks like ../../../etc/passwd.

    Args:
        path: The relative path to validate.
        base_dir: The base directory that the path must be within.

    Returns:
        True if the path is safe, False if it escapes the base directory.
    """
    from pathlib import Path

    if not path:
        return True  # Empty path is valid (root)

    # Resolve both paths and check if the target is within base_dir
    try:
        base = Path(base_dir).resolve()
        target = (base / path).resolve()
        target.relative_to(base)
        return True
    except (ValueError, OSError):
        return False


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

    # Remove or replace forbidden characters
    sanitized = []
    for char in filename:
        if char in FORBIDDEN_FILENAME_CHARS or char in CONTROL_CHARS:
            sanitized.append("_")  # Replace with underscore
        else:
            sanitized.append(char)
    filename = "".join(sanitized)

    # Remove problematic trailing characters
    filename = filename.rstrip(" .")

    # Truncate to maximum filename length (255 chars is typical limit)
    if len(filename) > 255:
        name, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
        max_name_len = 255 - len(ext) - 1  # -1 for the dot
        filename = name[:max_name_len] + "." + ext if ext else name[:255]

    # Handle empty or reserved names (RESERVED_FILENAMES uses uppercase)
    if not filename or filename.upper() in RESERVED_FILENAMES:
        filename = "unnamed"

    return filename


# =============================================================================
# Bucket Name Validation
# =============================================================================

# Canonical bucket-name pattern shared by client, server and desktop.
# Bucket names must be alphanumeric, may contain hyphens and underscores in
# the middle, but cannot start or end with a hyphen or underscore.
BUCKET_NAME_PATTERN = r"^[a-zA-Z0-9]([a-zA-Z0-9_-]*[a-zA-Z0-9])?$"

_BUCKET_NAME_RE = re.compile(BUCKET_NAME_PATTERN)


def is_valid_bucket_name(value: str) -> bool:
    """Validate a bucket name against the canonical HSYNC pattern.

    Bucket names must contain only alphanumeric characters, hyphens and
    underscores, and cannot start or end with a hyphen or underscore.

    Args:
        value: The bucket name to validate.

    Returns:
        True if the bucket name is valid, False otherwise.
    """
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
    from pathlib import Path

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
# merge-base state, deletion markers) using the sync channel itself.
INTERNAL_FILENAMES: frozenset[str] = frozenset(
    {
        ".hsyncignore",
        ".hsyncstate",
        ".hsynctombstones",
    }
)


def is_internal_name(name: str) -> bool:
    """Return True if *name* is an internal sync-engine artifact.

    Matches the basename against :data:`INTERNAL_FILENAMES` and the partial
    download suffix (``.part``). The per-peer sentinel ``.hsynckeep`` is NOT
    internal: it legitimately appears in delete events handled by clients.

    Args:
        name: A filename or path; only the basename is considered.

    Returns:
        True when the basename is an engine-owned artifact.
    """
    from hsync_common.constants import PARTIAL_DOWNLOAD_SUFFIX

    base = name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return base in INTERNAL_FILENAMES or base.endswith(PARTIAL_DOWNLOAD_SUFFIX)


def validate_remote_relpath(rel: str) -> str | None:
    """Validate a bucket-relative path received from a remote peer.

    Rejects (returns ``None`` for):
    - empty/non-string input, ``.`` and ``..`` components, absolute paths
      and Windows drive letters;
    - backslashes and any cross-platform forbidden/control characters
      (protects Windows peers from Linux-legal but hostile names);
    - Windows reserved names and problematic trailing characters in any
      path component;
    - internal sync-engine artifacts (see :data:`INTERNAL_FILENAMES`).

    Args:
        rel: The bucket-relative path to validate.

    Returns:
        The normalized relative path (leading/trailing slashes stripped)
        when safe, ``None`` otherwise.
    """
    if not rel or not isinstance(rel, str):
        return None

    # Absolute paths and drive letters are never acceptable on the wire.
    if not is_safe_path_component(rel):
        return None

    # Backslash and other cross-platform forbidden/control characters.
    if has_forbidden_chars(rel, FORBIDDEN_PATH_CHARS) or has_control_chars(rel):
        return None

    rel = rel.strip("/")
    if not rel:
        return None

    for part in rel.split("/"):
        if not part or part in (".", ".."):
            return None
        if is_reserved_name(part) or has_problematic_trailing(part):
            return None

    if is_internal_name(rel):
        return None

    return rel


def resolve_within(base_dir: str, rel: str) -> str | None:
    """Resolve a remote-supplied relative path inside *base_dir*.

    Combines lexical validation (:func:`validate_remote_relpath`) with
    filesystem confinement: the resolved path must remain within
    ``base_dir`` even after symlink resolution of existing components.

    Args:
        base_dir: The directory the path must stay within (e.g. the local
            bucket root).
        rel: The remote-supplied bucket-relative path.

    Returns:
        The confined absolute path, or ``None`` when the path is unsafe.
    """
    from pathlib import Path

    clean = validate_remote_relpath(rel)
    if clean is None:
        return None

    try:
        base = Path(base_dir).resolve()
        target = (base / clean).resolve()
        target.relative_to(base)
    except (OSError, ValueError):
        return None

    return str(target)


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
    from pathlib import Path

    if not target:
        return False

    bucket_path = Path(bucket_dir).resolve()
    if Path(target).is_absolute():
        target_resolved = Path(target).resolve()
    else:
        target_resolved = (Path(symlink_path).parent / target).resolve()

    try:
        target_resolved.relative_to(bucket_path)
        return True
    except ValueError:
        return False
