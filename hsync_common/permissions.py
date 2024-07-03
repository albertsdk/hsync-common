# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Canonical file-permission handling for HSYNC.

Permissions travel on the wire as an octal POSIX mode string (e.g. ``"644"``,
``"755"``), the same model used by rsync/Syncthing. The object type
(file/dir/symlink) is already carried by the :class:`File`/:class:`Dir`/
:class:`Symlink` models, so it is intentionally *not* encoded here.

This is the single source of truth shared by hsync-common, hsync-server and
hsync-client; the Android client mirrors the same format.
"""

from os import stat as os_stat
from re import fullmatch

# Permission bits we preserve: the standard rwx triplets plus the special bits
# (setuid/setgid/sticky). This mirrors the low 12 bits of ``st_mode``.
PERMISSION_MASK = 0o7777


def mode_to_octal(mode: int) -> str:
    """Convert a numeric ``st_mode`` to a canonical octal permission string.

    Args:
        mode: The numeric mode (e.g. ``os.stat().st_mode``).

    Returns:
        Octal permission string of at least three digits (e.g. ``"644"``,
        ``"4755"`` when special bits are set).
    """
    return format(mode & PERMISSION_MASK, "o").zfill(3)


def octal_to_mode(permissions: str) -> int:
    """Convert a canonical octal permission string to a numeric mode.

    Args:
        permissions: Octal permission string (e.g. ``"644"``, ``"0755"``).

    Returns:
        The numeric mode masked to the permission bits.
    """
    return int(permissions, 8) & PERMISSION_MASK


def is_valid_octal_permissions(permissions: str) -> bool:
    """Validate a canonical octal permission string.

    Accepts three or four octal digits (the optional leading digit carries the
    setuid/setgid/sticky bits).

    Args:
        permissions: Permission string to validate.

    Returns:
        True if the format is valid, False otherwise.
    """
    return bool(fullmatch(r"[0-7]{3,4}", permissions))


def get_permissions(obj_path: str) -> str:
    """Read a path's permissions as a canonical octal string.

    Args:
        obj_path: Path to the file or directory.

    Returns:
        Octal permission string (e.g. ``"644"``).
    """
    return mode_to_octal(os_stat(obj_path).st_mode)
