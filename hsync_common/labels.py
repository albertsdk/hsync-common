# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Shared action-label definitions and colorization for HSYNC projects.

Both ``hsync-client`` and ``hsync-server`` emit bracketed action labels
(e.g. ``[DOWNLOAD]``, ``[DELETE]``) in their log lines. This module is the
single source of truth for:

- The :class:`ActionLabel` enum (every label used across the projects).
- The :data:`LABEL_CATEGORIES` mapping (semantic category -> loguru color).
- The :data:`LABEL_STYLES` mapping (label -> color tags of its category).
- :func:`colorize_labels` (apply color tags to a log message).

**Two-level origin rule** (see ``docs/log-labels.md``):

- **Prefixed labels** are emitted during continuous watching:
  ``[LOCAL ...]`` marks an event originated by this node's local watcher,
  ``[REMOTE ...]`` an event caused by a peer (the master for a slave, a
  slave for the master, the central server in remote mode).
- **Unprefixed labels** belong to the reconciliation/full-scan phase,
  transfers, states and previews (e.g. ``[DOWNLOAD]``, ``[UPLOAD]``,
  ``[IN SYNC]``, ``[SKIP]``) and to ``hsync-server``'s own log lines.

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
- **Infrastructure** (magenta): transport-level messages (WebSocket, echo).
- **Phase** (bold white): lifecycle phase markers (initial sync started).
"""

from __future__ import annotations

from enum import StrEnum


class ActionLabel(StrEnum):
    """Single source of truth for the bracketed action labels in log lines.

    Labels are minimalist (no padding): the log line already carries a
    variable-width level token before the message, so column alignment is not
    achievable and dynamic-width tags keep the output clean and maintainable.
    """

    # ── Sync operations (unprefixed: reconciliation, transfers, server) ──
    DOWNLOAD = "[DOWNLOAD]"
    UPLOAD = "[UPLOAD]"
    RESUME = "[RESUME]"
    MOVE = "[MOVE]"
    DELETE = "[DELETE]"
    CREATE = "[CREATE]"
    MODIFY = "[MODIFY]"
    RENAME = "[RENAME]"
    PERMISSION = "[PERMISSION]"
    SYMLINK = "[SYMLINK]"
    IN_SYNC = "[IN SYNC]"
    SKIP = "[SKIP]"
    CONFLICT = "[CONFLICT]"
    GUARD = "[GUARD]"
    TOMBSTONE = "[TOMBSTONE]"

    # ── Preview (dry-run) ──────────────────────────────────────────────
    SYNCED = "[SYNCED]"
    TO_DOWNLOAD = "[TO DOWNLOAD]"
    TO_UPLOAD = "[TO UPLOAD]"
    TO_DELETE = "[TO DELETE]"
    TO_RENAME = "[TO RENAME]"

    # ── Local-origin watcher events (continuous watching) ──────────────
    LOCAL_CREATE = "[LOCAL CREATE]"
    LOCAL_MODIFY = "[LOCAL MODIFY]"
    LOCAL_RENAME = "[LOCAL RENAME]"
    LOCAL_DELETE = "[LOCAL DELETE]"
    LOCAL_SYMLINK = "[LOCAL SYMLINK]"
    LOCAL_SECURITY = "[LOCAL SECURITY]"
    LOCAL_IGNORE_DEL = "[LOCAL IGNORE DEL]"
    LOCAL_KEEP = "[LOCAL KEEP]"

    # ── Remote-origin events (inbound dispatch / peer-caused) ──────────
    REMOTE_CREATE = "[REMOTE CREATE]"
    REMOTE_MODIFY = "[REMOTE MODIFY]"
    REMOTE_RENAME = "[REMOTE RENAME]"
    REMOTE_DELETE = "[REMOTE DELETE]"
    REMOTE_SYMLINK = "[REMOTE SYMLINK]"
    REMOTE_IGNORE_DEL = "[REMOTE IGNORE DEL]"
    REMOTE_SECURITY = "[REMOTE SECURITY]"
    REMOTE_ECHO = "[REMOTE ECHO]"
    REMOTE_DOWNLOAD = "[REMOTE DOWNLOAD]"

    # ── Security / warnings ────────────────────────────────────────────
    SECURITY = "[SECURITY]"
    NO_MASTER = "[NO MASTER]"
    MASTER_CONFLICT = "[MASTER CONFLICT]"
    MASTER_TAKEOVER = "[MASTER TAKEOVER]"
    MASTER_YIELD = "[MASTER YIELD]"
    INSECURE_MASTER = "[INSECURE MASTER]"
    PAIRING_NEEDED = "[PAIRING NEEDED]"
    FINGERPRINT_CHANGED = "[FINGERPRINT CHANGED]"
    AUTH_REQUIRED = "[AUTH REQUIRED]"
    WATCHER_ERROR = "[WATCHER ERROR]"
    WATCHER_FALLBACK = "[WATCHER FALLBACK]"
    WATCHER_RESTORE = "[WATCHER RESTORE]"
    FD_EXHAUSTED = "[FD EXHAUSTED]"

    # ── Infrastructure (transport-level) ───────────────────────────────
    WS = "[WS]"

    # ── Lifecycle phase markers ────────────────────────────────────────
    INITIAL_SYNC = "[INITIAL SYNC]"

    # ── Readiness state (observable "ready for sync" threshold) ────────
    READY = "[READY]"


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
    "phase": ("<bold><white>", "</white></bold>"),
}

#: Label -> category name. Every :class:`ActionLabel` must be listed here.
_LABEL_CATEGORY_MAP: dict[str, str] = {
    ActionLabel.DOWNLOAD: "transfer",
    ActionLabel.RESUME: "transfer",
    ActionLabel.TO_DOWNLOAD: "transfer",
    ActionLabel.REMOTE_DOWNLOAD: "transfer",
    ActionLabel.UPLOAD: "upload",
    ActionLabel.TO_UPLOAD: "upload",
    ActionLabel.CREATE: "create",
    ActionLabel.SYMLINK: "create",
    ActionLabel.LOCAL_CREATE: "create",
    ActionLabel.REMOTE_CREATE: "create",
    ActionLabel.LOCAL_SYMLINK: "create",
    ActionLabel.REMOTE_SYMLINK: "create",
    ActionLabel.MODIFY: "modify",
    ActionLabel.LOCAL_MODIFY: "modify",
    ActionLabel.REMOTE_MODIFY: "modify",
    ActionLabel.MOVE: "rename",
    ActionLabel.RENAME: "rename",
    ActionLabel.TO_RENAME: "rename",
    ActionLabel.LOCAL_RENAME: "rename",
    ActionLabel.REMOTE_RENAME: "rename",
    ActionLabel.DELETE: "delete",
    ActionLabel.TO_DELETE: "delete",
    ActionLabel.LOCAL_DELETE: "delete",
    ActionLabel.REMOTE_DELETE: "delete",
    ActionLabel.PERMISSION: "permission",
    ActionLabel.IN_SYNC: "in_sync",
    ActionLabel.SKIP: "in_sync",
    ActionLabel.SYNCED: "in_sync",
    ActionLabel.LOCAL_KEEP: "in_sync",
    ActionLabel.LOCAL_IGNORE_DEL: "warning",
    ActionLabel.REMOTE_IGNORE_DEL: "warning",
    ActionLabel.GUARD: "warning",
    ActionLabel.CONFLICT: "warning",
    ActionLabel.TOMBSTONE: "warning",
    ActionLabel.NO_MASTER: "warning",
    ActionLabel.MASTER_CONFLICT: "warning",
    ActionLabel.MASTER_TAKEOVER: "warning",
    ActionLabel.MASTER_YIELD: "warning",
    ActionLabel.INSECURE_MASTER: "warning",
    ActionLabel.PAIRING_NEEDED: "warning",
    ActionLabel.FINGERPRINT_CHANGED: "warning",
    ActionLabel.AUTH_REQUIRED: "warning",
    ActionLabel.WATCHER_ERROR: "warning",
    ActionLabel.WATCHER_FALLBACK: "warning",
    ActionLabel.WATCHER_RESTORE: "create",
    ActionLabel.FD_EXHAUSTED: "warning",
    ActionLabel.SECURITY: "security",
    ActionLabel.LOCAL_SECURITY: "security",
    ActionLabel.REMOTE_SECURITY: "security",
    ActionLabel.WS: "infrastructure",
    ActionLabel.REMOTE_ECHO: "infrastructure",
    ActionLabel.INITIAL_SYNC: "phase",
    ActionLabel.READY: "create",
}

#: Label -> (start_tag, end_tag) loguru color tags, derived from categories.
LABEL_STYLES: dict[str, tuple[str, str]] = {
    label: LABEL_CATEGORIES[category] for label, category in _LABEL_CATEGORY_MAP.items()
}

#: ``LABEL_STYLES`` items ordered longest-first. Precomputed once at import so
#: :func:`colorize_labels` no longer re-sorts the table for every log line.
_STYLES_LONGEST_FIRST: tuple[tuple[str, tuple[str, str]], ...] = tuple(
    sorted(LABEL_STYLES.items(), key=lambda item: len(item[0]), reverse=True)
)


def colorize_labels(message: str, use_colors: bool = True) -> str:
    """Add color tags to action labels in *message*.

    Labels are matched by longest-first to prevent short labels from
    being substituted inside their longer counterparts (e.g.
    ``[DOWNLOAD]`` inside ``[REMOTE DOWNLOAD]``). Only exact occurrences
    are replaced.

    Args:
        message: The log message to colorize.
        use_colors: Whether to apply colors (False for plain output).

    Returns:
        Message with color tags applied to action labels.
    """
    if not use_colors:
        return message

    # Longest-first avoids substring corruption:
    # "[REMOTE DOWNLOAD]" must be processed before "[DOWNLOAD]".
    for label, (start_tag, end_tag) in _STYLES_LONGEST_FIRST:
        if label in message:
            message = message.replace(label, f"{start_tag}{label}{end_tag}")
    return message


def resolve_label(prefix: str, name: str) -> str:
    """Resolve the bracketed label string for *name*, honouring an optional *prefix*.

    Labels follow a **two-level origin rule** (see ``docs/log-labels.md``):

    - ``"LOCAL "`` / ``"REMOTE "`` prefixes mark events during continuous
      watching (local watcher vs peer-caused / inbound dispatch);
    - the empty prefix ``""`` is reserved for the reconciliation/full-scan
      phase, transfers, states, previews and ``hsync-server``'s own log
      lines (e.g. ``[DOWNLOAD]``, ``[UPLOAD]``, ``[IN SYNC]``).

    The label is resolved through :class:`ActionLabel` so that
    :func:`colorize_labels` can match and colorize it. The mapping is:

    - ``prefix=""``, ``name="CREATE"``        -> ``[CREATE]`` (``ActionLabel.CREATE``)
    - ``prefix="LOCAL "``, ``name="CREATE"``  -> ``[LOCAL CREATE]`` (``ActionLabel.LOCAL_CREATE``)
    - ``prefix="REMOTE "``, ``name="DELETE"`` -> ``[REMOTE DELETE]`` (``ActionLabel.REMOTE_DELETE``)

    A prefixed name maps to the ``<PREFIX>_<NAME>`` member (e.g.
    ``REMOTE DELETE`` -> ``REMOTE_DELETE``, ``LOCAL IGNORE DEL`` ->
    ``LOCAL_IGNORE_DEL``); an unprefixed name maps to ``<NAME>``. When no
    member matches (e.g. an internal debug tag without a registered label),
    the label is interpolated verbatim so it still prints, just uncolored.

    This is the single helper used by both the watchdog handlers
    (``BaseFileEventHandler._label``) and the inbound event dispatcher
    (``_tag``) so the two transports cannot drift apart.

    Args:
        prefix: Optional log prefix (``""``, ``"LOCAL "`` or ``"REMOTE "``).
        name: Label stem without brackets (e.g. ``"CREATE"``, ``"IGNORE DEL"``).

    Returns:
        The resolved bracketed label string.
    """
    prefix = prefix.strip()
    # Normalise the stem once (was computed twice for prefixed labels).
    stem = name.replace(" ", "_")
    if prefix:
        key = f"{prefix.replace(' ', '_').upper()}_{stem}"
        member = getattr(ActionLabel, key, None)
        if member is not None:
            return str(member)
    member = getattr(ActionLabel, stem, None)
    if member is not None:
        return str(member)
    return f"[{prefix} {name}]" if prefix else f"[{name}]"
