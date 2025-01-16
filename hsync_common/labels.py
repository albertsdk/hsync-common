# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Shared action-label definitions and colorization for HSYNC projects.

Both ``hsync-client`` and ``hsync-server`` emit bracketed action labels
(e.g. ``[DOWNLOAD]``, ``[DELETE]``) in their log lines. This module is the
single source of truth for:

- The :class:`ActionLabel` enum (every label used across the projects).
- The :data:`LABEL_CATEGORIES` mapping (semantic category -> loguru color).
- The :data:`LABEL_STYLES` mapping (label -> color tags of its category).
- :func:`colorize_labels` (apply color tags to a log message).

Labels are grouped into **semantic categories** so the output is not a
rainbow where every label has a different color, but a small set of
distinct colors that convey the *kind* of operation at a glance:

- **Transfer** (cyan): data moving in (downloads, resumes).
- **Upload** (green): data moving out (uploads).
- **Create** (green): additive operations (create, symlink).
- **Modify** (blue): content changes.
- **Rename** (blue): moves/renames.
- **Delete** (red): destructive operations.
- **Permission** (magenta): permission changes.
- **In-sync/Skip** (dim): no-op operations.
- **Warning/Guard** (yellow): guards, conflicts, security warnings, ignored
  deletions.
- **Security** (red): rejected unsafe paths.
- **Infrastructure** (magenta): transport-level messages (WebSocket, LAN).
"""

from __future__ import annotations

from enum import StrEnum


class ActionLabel(StrEnum):
    """Single source of truth for the bracketed action labels in log lines.

    Labels are minimalist (no padding): the log line already carries a
    variable-width level token before the message, so column alignment is not
    achievable and dynamic-width tags keep the output clean and maintainable.
    """

    # ── Sync operations ────────────────────────────────────────────────
    DOWNLOAD = "[DOWNLOAD]"
    UPLOAD = "[UPLOAD]"
    RESUME = "[RESUME]"
    MOVE = "[MOVE]"
    REMOVE = "[REMOVE]"
    DELETE = "[DELETE]"
    CREATE = "[CREATE]"
    MODIFY = "[MODIFY]"
    RENAME = "[RENAME]"
    PERMISSION = "[PERMISSION]"
    SYMLINK = "[SYMLINK]"
    IN_SYNC = "[IN SYNC]"
    SKIP = "[SKIP]"
    IGNORE_DEL = "[IGNORE DEL]"
    CONFLICT = "[CONFLICT]"
    GUARD = "[GUARD]"
    TOMBSTONE = "[TOMBSTONE]"

    # ── Preview (dry-run) ──────────────────────────────────────────────
    SYNCED = "[SYNCED]"
    TO_DOWNLOAD = "[TO DOWNLOAD]"
    TO_UPLOAD = "[TO UPLOAD]"
    TO_DELETE = "[TO DELETE]"
    TO_RENAME = "[TO RENAME]"

    # ── LAN client operations ──────────────────────────────────────────
    CLIENT_UP = "[CLIENT UP]"
    CLIENT_DEL = "[CLIENT DEL]"
    CLIENT_REN = "[CLIENT REN]"
    CLIENT_DIR = "[CLIENT DIR]"
    CLIENT_NEW = "[CLIENT NEW]"
    CLIENT_KEEP = "[CLIENT KEEP]"
    CLIENT_IGN = "[CLIENT IGN]"

    # ── LAN master broadcast ───────────────────────────────────────────
    LAN_MODIFY = "[LAN MODIFY]"
    LAN_CREATE = "[LAN CREATE]"
    LAN_RENAME = "[LAN RENAME]"
    LAN_REMOVE = "[LAN REMOVE]"
    LAN_SYMLINK = "[LAN SYMLINK]"
    LAN_DELETE = "[LAN DELETE]"
    LAN_IGNORE_DEL = "[LAN IGNORE DEL]"
    LAN_SECURITY = "[LAN SECURITY]"
    LAN_ECHO = "[LAN ECHO]"

    # ── Security / warnings ────────────────────────────────────────────
    SECURITY = "[SECURITY]"
    NO_MASTER = "[NO MASTER]"
    MASTER_CONFLICT = "[MASTER CONFLICT]"
    MASTER_TAKEOVER = "[MASTER TAKEOVER]"
    INSECURE_MASTER = "[INSECURE MASTER]"
    PAIRING_NEEDED = "[PAIRING NEEDED]"
    FINGERPRINT_CHANGED = "[FINGERPRINT CHANGED]"
    AUTH_REQUIRED = "[AUTH REQUIRED]"

    # ── Infrastructure (transport-level) ───────────────────────────────
    WS = "[WS]"


# =============================================================================
# Color categories
# =============================================================================

#: Category -> (start_tag, end_tag) loguru color tags.
LABEL_CATEGORIES: dict[str, tuple[str, str]] = {
    "transfer": ("<cyan>", "</cyan>"),
    "upload": ("<green>", "</green>"),
    "create": ("<green>", "</green>"),
    "modify": ("<blue>", "</blue>"),
    "rename": ("<blue>", "</blue>"),
    "delete": ("<red>", "</red>"),
    "permission": ("<magenta>", "</magenta>"),
    "in_sync": ("<dim>", "</dim>"),
    "warning": ("<yellow>", "</yellow>"),
    "security": ("<red>", "</red>"),
    "infrastructure": ("<magenta>", "</magenta>"),
}

#: Label -> category name. Every :class:`ActionLabel` must be listed here.
_LABEL_CATEGORY_MAP: dict[str, str] = {
    ActionLabel.DOWNLOAD: "transfer",
    ActionLabel.RESUME: "transfer",
    ActionLabel.TO_DOWNLOAD: "transfer",
    ActionLabel.UPLOAD: "upload",
    ActionLabel.TO_UPLOAD: "upload",
    ActionLabel.CLIENT_UP: "upload",
    ActionLabel.CREATE: "create",
    ActionLabel.SYMLINK: "create",
    ActionLabel.CLIENT_NEW: "create",
    ActionLabel.CLIENT_DIR: "create",
    ActionLabel.LAN_CREATE: "create",
    ActionLabel.LAN_SYMLINK: "create",
    ActionLabel.MODIFY: "modify",
    ActionLabel.LAN_MODIFY: "modify",
    ActionLabel.MOVE: "rename",
    ActionLabel.RENAME: "rename",
    ActionLabel.TO_RENAME: "rename",
    ActionLabel.CLIENT_REN: "rename",
    ActionLabel.LAN_RENAME: "rename",
    ActionLabel.REMOVE: "delete",
    ActionLabel.DELETE: "delete",
    ActionLabel.TO_DELETE: "delete",
    ActionLabel.CLIENT_DEL: "delete",
    ActionLabel.LAN_REMOVE: "delete",
    ActionLabel.LAN_DELETE: "delete",
    ActionLabel.PERMISSION: "permission",
    ActionLabel.IN_SYNC: "in_sync",
    ActionLabel.SKIP: "in_sync",
    ActionLabel.SYNCED: "in_sync",
    ActionLabel.CLIENT_KEEP: "in_sync",
    ActionLabel.IGNORE_DEL: "warning",
    ActionLabel.CLIENT_IGN: "warning",
    ActionLabel.LAN_IGNORE_DEL: "warning",
    ActionLabel.GUARD: "warning",
    ActionLabel.CONFLICT: "warning",
    ActionLabel.TOMBSTONE: "warning",
    ActionLabel.NO_MASTER: "warning",
    ActionLabel.MASTER_CONFLICT: "warning",
    ActionLabel.MASTER_TAKEOVER: "warning",
    ActionLabel.INSECURE_MASTER: "warning",
    ActionLabel.PAIRING_NEEDED: "warning",
    ActionLabel.FINGERPRINT_CHANGED: "warning",
    ActionLabel.AUTH_REQUIRED: "warning",
    ActionLabel.SECURITY: "security",
    ActionLabel.LAN_SECURITY: "security",
    ActionLabel.WS: "infrastructure",
    ActionLabel.LAN_ECHO: "infrastructure",
}

#: Label -> (start_tag, end_tag) loguru color tags, derived from categories.
LABEL_STYLES: dict[str, tuple[str, str]] = {
    label: LABEL_CATEGORIES[category] for label, category in _LABEL_CATEGORY_MAP.items()
}


def colorize_labels(message: str, use_colors: bool = True) -> str:
    """Add color tags to action labels in *message*.

    Args:
        message: The log message to colorize.
        use_colors: Whether to apply colors (False for plain output).

    Returns:
        Message with color tags applied to action labels.
    """
    if not use_colors:
        return message

    for label, (start_tag, end_tag) in LABEL_STYLES.items():
        if label in message:
            message = message.replace(label, f"{start_tag}{label}{end_tag}")
    return message


def resolve_label(prefix: str, name: str) -> str:
    """Resolve the bracketed label string for *name*, honouring an optional *prefix*.

    The label is resolved through :class:`ActionLabel` so that
    :func:`colorize_labels` can match and colorize it. The mapping is:

    - ``prefix=""``, ``name="CREATE"``     -> ``[CREATE]`` (``ActionLabel.CREATE``)
    - ``prefix="LAN "``, ``name="CREATE"`` -> ``[LAN CREATE]`` (``ActionLabel.LAN_CREATE``)
    - ``prefix=""``, ``name="IGNORE DEL"`` -> ``[IGNORE DEL]`` (``ActionLabel.IGNORE_DEL``)

    A LAN-prefixed name maps to the ``LAN_<NAME>`` member (e.g. ``LAN CREATE`` ->
    ``LAN_CREATE``); an unprefixed name maps to ``<NAME>``. When no member matches
    (e.g. an internal debug tag without a registered label), the label is
    interpolated verbatim so it still prints, just uncolored.

    This is the single helper used by both the watchdog handlers
    (``BaseFileEventHandler._label``) and the inbound event dispatcher
    (``_tag``) so the two transports cannot drift apart.

    Args:
        prefix: Optional log prefix (e.g. ``""`` or ``"LAN "``).
        name: Label stem without brackets (e.g. ``"CREATE"``, ``"IGNORE DEL"``).

    Returns:
        The resolved bracketed label string.
    """
    prefix = prefix.strip()
    if prefix:
        key = f"{prefix.replace(' ', '_').upper()}_{name.replace(' ', '_')}"
        member = getattr(ActionLabel, key, None)
        if member is not None:
            return str(member)
    member = getattr(ActionLabel, name.replace(" ", "_"), None)
    if member is not None:
        return str(member)
    return f"[{prefix} {name}]" if prefix else f"[{name}]"
