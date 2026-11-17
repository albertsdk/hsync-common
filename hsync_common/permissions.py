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

import os
import re
import stat
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

# Windows cannot represent POSIX modes: NTFS carries only the read-only
# attribute. The wire stays POSIX; this process maps the owner-write bit to that
# attribute and exposes a canonical mode so peers never see 666/777
# (``get_permissions``). Module constant so tests can drive the Windows branch.
_IS_WINDOWS = os.name == "nt"

# The canonical modes a lossy local reports on the wire.
_WINDOWS_FILE_WRITABLE = "644"
_WINDOWS_FILE_READONLY = "444"
_WINDOWS_DIRECTORY = "755"


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


def canonical_permissions(st: os.stat_result) -> str:
    """Return a stat result's canonical octal mode, mapped on a lossy host.

    The Windows mapping lives here so every listing/upload metadata path
    (``get_permissions``, ``File.get``, ``Dir.get``) emits the same canonical
    modes instead of the synthetic NTFS 666/777. Consumers: ``hsync-common``
    models and ``get_permissions``; ``hsync-client`` and ``hsync-server``
    through them.
    """
    if not _IS_WINDOWS:
        return mode_to_octal(st.st_mode)
    writable = bool(st.st_mode & stat.S_IWRITE)
    if stat.S_ISDIR(st.st_mode):
        return _WINDOWS_DIRECTORY if writable else "555"
    return _WINDOWS_FILE_WRITABLE if writable else _WINDOWS_FILE_READONLY


def get_permissions(obj_path: str) -> str:
    """Read a path's permissions as a canonical octal string.

    On Windows only the read-only attribute is representable, so the mode is
    reported canonically (``644``/``755``, or ``444``/``555`` when the attribute
    is set): exposing the synthetic NTFS 666/777 to a POSIX peer would make it
    apply over-permissive modes.

    Consumers: ``hsync-client`` (``File``/``Dir`` metadata, permission-only
    events), ``hsync-server`` (listing/upload metadata).

    Args:
        obj_path: Path to the file or directory.

    Returns:
        Octal permission string (e.g. ``"644"``).
    """
    return canonical_permissions(os_stat(obj_path))


def local_permissions_are_lossy() -> bool:
    """Return whether this host can represent only the owner-write bit.

    True on Windows (NTFS carries the read-only attribute, not POSIX modes).
    Consumers: the client's capability advertisement
    (``hsync_client/capabilities.py::local_capabilities``), the P2P mDNS TXT
    record and the reconciliation projection
    (``hsync_client/sync.py::_actions_from_remote``).
    """
    return _IS_WINDOWS


def has_owner_write(permissions: str) -> bool:
    """Return whether the owner-write bit is set in *permissions*.

    The Windows-portable projection of a POSIX mode: a lossy peer can only
    represent writable vs read-only, so the reconciliation compares this bit
    instead of the full string when either side is lossy.

    Consumers: ``hsync-client/sync.py::_actions_from_remote``.
    """
    try:
        return bool(octal_to_mode(permissions) & 0o200)
    except (TypeError, ValueError):
        return False


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
    if _IS_WINDOWS:
        return _apply_windows_permissions(
            obj_path, sanitized, directory=directory, skip_if_equal=skip_if_equal
        )
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


def _apply_windows_permissions(
    obj_path: str, sanitized: str, *, directory: bool, skip_if_equal: bool
) -> str | None:
    """Map a wire mode to NTFS's only portable bit: the read-only attribute.

    Directories always stay writable (the sync engine must traverse and update
    its own tree), so their owner-write floor is not representable as read-only.
    A file is read-only exactly when the wire mode lacks the owner-write bit.
    Returns the canonical mode actually in force, or ``None`` when
    *skip_if_equal* found it already applied.
    """
    if directory:
        target = _WINDOWS_DIRECTORY
    else:
        target = _WINDOWS_FILE_WRITABLE if has_owner_write(sanitized) else _WINDOWS_FILE_READONLY
    if skip_if_equal:
        try:
            if get_permissions(obj_path) == target:
                return None
        except OSError:
            pass  # missing path: let chmod raise the real error
    chmod(obj_path, stat.S_IWRITE if target != _WINDOWS_FILE_READONLY else stat.S_IREAD)
    return target
