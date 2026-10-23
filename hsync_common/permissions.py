# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Canonical file-permission handling for HSYNC.

Permissions travel on the wire as an octal POSIX mode string (e.g. ``"644"``,
``"755"``), the same model used by rsync/Syncthing. The object type
(file/dir/symlink) is already carried by the :class:`File`/:class:`Dir`/
:class:`Symlink` models, so it is intentionally *not* encoded here.

This is the single source of truth shared by hsync-common, hsync-server and
hsync-client; the Android client mirrors the same format.
:func:`apply_remote_permissions` is the single *receiver-side* applier (server
upload/download/delta, client download/metadata events).
"""

import re
from os import chmod
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


def apply_remote_permissions(
    obj_path: str,
    permissions: str,
    *,
    directory: bool = False,
    skip_if_equal: bool = False,
) -> str | None:
    """Apply a wire-supplied permission string to a local path.

    Single implementation of the *receiver* rule shared by ``hsync-server`` and
    ``hsync-client`` (full upload, download, delta apply, metadata events):
    sanitize the peer value, convert it to a mode, OR the owner-access floor in
    for directories, then chmod. Keeping it here means the security policy —
    special bits stripped, owner always able to traverse its own storage —
    cannot drift between the two receivers.

    Args:
        obj_path: File or directory to update.
        permissions: Octal permission string received from a peer.
        directory: Apply the :data:`OWNER_DIRECTORY_ACCESS` floor (directory
            targets). A peer-supplied ``000`` must never lock the receiver out
            of its own storage.
        skip_if_equal: Skip the ``chmod`` syscall when the current mode already
            matches (used by the client, which re-applies modes on every event).

    Returns:
        The octal mode actually applied, or ``None`` when *skip_if_equal* found
        the mode already in place.

    Raises:
        ValueError: If *permissions* is not a valid octal permission string.
    """
    sanitized = sanitize_remote_permissions(permissions)
    if skip_if_equal:
        try:
            if mode_to_octal(os_stat(obj_path).st_mode) == sanitized:
                return None
        except OSError:
            pass  # missing path: let chmod raise the real error
    mode = octal_to_mode(sanitized)
    if directory:
        mode |= OWNER_DIRECTORY_ACCESS
    chmod(obj_path, mode)
    return sanitized
