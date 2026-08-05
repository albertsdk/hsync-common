# Log Action Labels — Reference

Every HSYNC project emits **bracketed action labels** at the start of a log
message (e.g. `[DOWNLOAD]`, `[NO MASTER]`) to tag the kind of operation or
event. This document is the **canonical catalog** of all labels, their meaning,
their color category, and which projects can emit them.

> The machine source of truth for label *values* is the `ActionLabel` enum in
> [`hsync_common/labels.py`](../hsync_common/labels.py). This page is the
> human-readable companion: when a label is added/renamed there, update this
> page in the same change.

## How labels work

- A label is a short, bracketed token: `[DOWNLOAD]`, `[IGNORE DEL]`,
  `[LAN CREATE]`. Multi-word labels use **spaces** (never underscores).
- Labels are grouped into **semantic color categories** so the log conveys the
  *kind* of operation at a glance, not a rainbow of one color per label.
- In terminals/terminals-with-color the label is wrapped in the category color;
  in plain output (files, `--no-color`, non-TTY) the label is emitted as-is.
- The Android client mirrors the same labels in its `LogAction` enum and colors
  them in the in-app log panel by the same categories.

## Color categories

| Category | Color | Meaning |
|----------|-------|---------|
| transfer | cyan | data moving in (downloads, resumes) |
| upload | green | data moving out (uploads) |
| create | green | additive operations (create, symlink) |
| modify | blue | content changes |
| rename | blue | moves / renames |
| delete | red | destructive operations |
| permission | magenta | permission changes |
| in_sync | dim | no-op (already in sync, skipped) |
| warning | yellow | guards, conflicts, ignored deletions, LAN trust warnings |
| security | red | rejected unsafe paths / hard security refusals |
| infrastructure | magenta | transport-level (WebSocket, LAN echo) |

## Projects that emit labels

| Code | Project | Notes |
|------|---------|-------|
| **C** | `hsync-client` | CLI; broadest set (server-mode + LAN client/master) |
| **S** | `hsync-server` | REST + WebSocket relay |
| **A** | `hsync-android` | mirrors the full enum; log panel can show any label |
| **D** | `hsync-desktop` | displays the client subprocess logs + a few own markers |

---

## Sync operations

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[DOWNLOAD]` | transfer | Downloading a file from server / master | ✓ | ✓ | ✓ | ✓ |
| `[UPLOAD]` | upload | Uploading a file to server / master | ✓ | ✓ | ✓ | ✓ |
| `[RESUME]` | transfer | Resuming a partial upload or download | ✓ | | ✓ | ✓ |
| `[MOVE]` | rename | Renaming/moving a file or directory (watchdog detection) | ✓ | | ✓ | ✓ |
| `[REMOVE]` | delete | Removing a file or directory | ✓ | | ✓ | ✓ |
| `[DELETE]` | delete | Deleting a local file not present on master (LAN); server delete endpoint | ✓ | ✓ | ✓ | ✓ |
| `[CREATE]` | create | Creating a directory | ✓ | ✓ | ✓ | ✓ |
| `[MODIFY]` | modify | File or directory content modified | ✓ | ✓ | ✓ | ✓ |
| `[RENAME]` | rename | Rename/move applied to a file or directory | ✓ | ✓ | ✓ | ✓ |
| `[PERMISSION]` | permission | Setting file / directory permissions | ✓ | | ✓ | ✓ |
| `[SYMLINK]` | create | Creating a symbolic link | ✓ | ✓ | ✓ | ✓ |
| `[IN SYNC]` | in_sync | File already in sync (no action required) | ✓ | | ✓ | ✓ |
| `[SKIP]` | in_sync | File skipped | ✓ | | ✓ | ✓ |
| `[IGNORE DEL]` | warning | Deletion ignored (ignore-delete / backup mode) | ✓ | | ✓ | ✓ |
| `[CONFLICT]` | warning | File conflict detected (three-way merge) | ✓ | | ✓ | ✓ |
| `[GUARD]` | warning | Mass-deletion guard tripped (deletions paused) | ✓ | | ✓ | ✓ |
| `[TOMBSTONE]` | warning | File deleted remotely while offline; local copy removed | ✓ | | ✓ | ✓ |

## Preview (dry-run)

These appear only with `--preview` / dry-run. They describe what *would*
happen, not what happened.

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[SYNCED]` | in_sync | File is in sync (preview result) | ✓ | | ✓ | ✓ |
| `[TO DOWNLOAD]` | transfer | File would be downloaded | ✓ | | ✓ | ✓ |
| `[TO UPLOAD]` | upload | File would be uploaded | ✓ | | ✓ | ✓ |
| `[TO DELETE]` | delete | File would be deleted | ✓ | | ✓ | ✓ |
| `[TO RENAME]` | rename | File would be renamed | ✓ | | ✓ | ✓ |

## LAN client operations

Emitted by a LAN **client** (slave) when it pushes local changes to the elected
master.

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[CLIENT UP]` | upload | Client uploads a file to the master | ✓ | | ✓ | ✓ |
| `[CLIENT DEL]` | delete | Client deletes a file on the master | ✓ | | ✓ | ✓ |
| `[CLIENT REN]` | rename | Client renames a file on the master | ✓ | | ✓ | ✓ |
| `[CLIENT DIR]` | create | Client creates a directory on the master | ✓ | | ✓ | ✓ |
| `[CLIENT NEW]` | create | Client creates a new file on the master | ✓ | | ✓ | ✓ |
| `[CLIENT KEEP]` | in_sync | Client creates a sentinel file (`.hsynckeep`) | ✓ | | ✓ | ✓ |
| `[CLIENT IGN]` | warning | Client ignores a deletion (ignore-delete mode) | ✓ | | ✓ | ✓ |

## LAN master broadcasts

Emitted by the LAN **master** when it broadcasts a filesystem event to its
slaves (they then pull/apply the change).

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[LAN MODIFY]` | modify | Master broadcasts a file modification (slaves pull new bytes). The trigger `(closed)`/`(modified)` shows whether it fired from `IN_CLOSE_WRITE` (reliable) or the `on_modified` debounce fallback; `(dir)` marks a directory metadata event (inotify `IN_ATTRIB` on the parent when a child is created/written/renamed/removed) — directory `MODIFY` lines are stat-deduplicated so only genuine mtime changes propagate | ✓ | | ✓ | ✓ |
| `[LAN CREATE]` | create | Master broadcasts a directory creation | ✓ | | ✓ | ✓ |
| `[LAN RENAME]` | rename | Master broadcasts a rename/move | ✓ | | ✓ | ✓ |
| `[LAN REMOVE]` | delete | Master broadcasts a removal | ✓ | | ✓ | ✓ |
| `[LAN SYMLINK]` | create | Master broadcasts a symbolic link creation | ✓ | | ✓ | ✓ |
| `[LAN DELETE]` | delete | Master broadcasts a deletion | ✓ | | ✓ | ✓ |
| `[LAN IGNORE DEL]` | warning | Master ignores a deletion (ignore-delete mode) | ✓ | | ✓ | ✓ |
| `[LAN SECURITY]` | security | Master rejected an unsafe inbound path | ✓ | | ✓ | ✓ |
| `[LAN ECHO]` | infrastructure | Master echoed a slave-originated event back to the other slaves | ✓ | | ✓ | ✓ |

## Security & warnings

Emitted when a security or trust condition is hit. These usually drive a UI
notification in desktop/Android.

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[SECURITY]` | security | Rejected an unsafe remote path (traversal, absolute, internal name) | ✓ | ✓ | ✓ | ✓ |
| `[NO MASTER]` | warning | No master elected after the grace period (all peers are `--never-master`) | ✓ | | ✓ | ✓ |
| `[MASTER CONFLICT]` | warning | Two `force_master` peers conflict; one wins by earlier start time | ✓ | | ✓ | ✓ |
| `[MASTER TAKEOVER]` | warning | A remote `force_master` peer takes over a non-force_master master | ✓ | | ✓ | ✓ |
| `[INSECURE MASTER]` | warning | Master does not advertise HTTPS + a cert fingerprint; connection refused | ✓ | | ✓ | ✓ |
| `[PAIRING NEEDED]` | warning | Strict pairing: master cert is unpinned; out-of-band confirmation required | ✓ | | ✓ | ✓ |
| `[FINGERPRINT CHANGED]` | warning | Master cert no longer matches the pinned fingerprint (possible MITM); refused | ✓ | | ✓ | ✓ |
| `[AUTH REQUIRED]` | warning | Non-interactive LAN write lacks `HSYNC_LAN_KEY`; set it or run interactively | ✓ | | ✓ | ✓ |

## Infrastructure (transport-level)

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[WS]` | infrastructure | WebSocket transport message (e.g. dropping a dead connection) | | ✓ | ✓ | |

---

## Desktop-only markers

The desktop GUI is not an engine: it runs the `hsync-client` subprocess and
surfaces its logs, so every client label above can appear in the desktop log
panel. It also emits a few **own** markers (not part of `ActionLabel`):

| Marker | Meaning |
|--------|---------|
| `[NO MASTER]` | surfaced from the client's `no_master` structured event (same meaning as the client label) |
| `[EVENT ERROR]` | the desktop's own prefix for an error event from the engine/UI layer |

## Legend in the CLI

Run `hsync-client --legend` (or `--help-symbols`) to print the label legend
directly in the terminal.
