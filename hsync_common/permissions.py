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

import re
from os import stat as os_stat

# Permission bits we preserve: the standard rwx triplets plus the special bits
# (setuid/setgid/sticky). This mirrors the low 12 bits of ``st_mode``.
PERMISSION_MASK = 0o7777

# Permission bits accepted from a remote peer: only the rwx triplets.
# setuid/setgid/sticky bits must never be applied on behalf of a remote
# peer — a synced file carrying ``4755`` would otherwise become a setuid
# executable on every receiving host (a local privilege-escalation vector
# when the daemon runs with elevated privileges).
REMOTE_PERMISSION_MASK = 0o777

# Owner-access floor OR-ed onto directory modes applied from a remote peer.
# A peer-supplied mode like ``000`` must never lock every receiver out of its
# own storage: the owner always keeps rwx so the sync engine (and the server's
# storage layer) can still traverse and update its own tree.
OWNER_DIRECTORY_ACCESS = 0o700

# Precompiled octal-permission shape gate (3 or 4 octal digits): a single
# C-level regex object instead of recompiling (or cache-looking-up) the
# pattern on every validation call.
_OCTAL_PERMISSIONS_RE = re.compile(r"[0-7]{3,4}")


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
    return bool(_OCTAL_PERMISSIONS_RE.fullmatch(permissions))


def sanitize_remote_permissions(permissions: str) -> str:
    """Strip special bits (setuid/setgid/sticky) from wire-supplied permissions.

    Use this on any permission string received from a remote peer before
    applying it to the local filesystem. The rwx triplets are preserved.

    Args:
        permissions: Octal permission string from a remote peer.

    Returns:
        Octal permission string masked to :data:`REMOTE_PERMISSION_MASK`.

    Raises:
        ValueError: If the string is not a valid octal permission.
    """
    if not is_valid_octal_permissions(permissions):
        raise ValueError(f"Invalid octal permissions: {permissions!r}")
    return format(int(permissions, 8) & REMOTE_PERMISSION_MASK, "o").zfill(3)


def get_permissions(obj_path: str) -> str:
    """Read a path's permissions as a canonical octal string.

    Args:
        obj_path: Path to the file or directory.

    Returns:
        Octal permission string (e.g. ``"644"``).
    """
    return mode_to_octal(os_stat(obj_path).st_mode)
