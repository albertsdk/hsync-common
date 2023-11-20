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

    if not is_safe_path_component(filename):
        return False

    return True


def is_safe_path_component(path: str) -> bool:
    """
    Check if a path component is safe (no path traversal or absolute paths).

    This function prevents path traversal attacks by ensuring the path:
    - Does not contain ".." (parent directory references)
    - Is not an absolute path (doesn't start with / or drive letter)
    - Doesn't contain Windows drive letter references (C:, D:, etc.)

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

    # Check for parent directory traversal
    if ".." in path:
        return False

    # Normalize and check again (handles encoded traversals)
    normalized = path.replace("\\", "/").replace("//", "/")
    if ".." in normalized:
        return False

    return True


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

    # Handle empty or reserved names
    if not filename or filename.lower() in RESERVED_FILENAMES:
        filename = "unnamed"

    return filename
