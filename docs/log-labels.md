# Log Action Labels — Reference

Every HSYNC project emits **bracketed action labels** at the start of a log
message (e.g. `[DOWNLOAD]`, `[NO MASTER]`) to tag the kind of operation or
event. This document is the **canonical catalog** of all labels, their meaning,
their color category, and which projects can emit them.

> The machine source of truth for label *values* is the `ActionLabel` enum in
> [`hsync_common/labels.py`](../hsync_common/labels.py). This page is the
> human-readable companion: when a label is added/renamed there, update this
> page in the same change.

## The two-level origin rule

Labels follow a strict two-level rule:

- **Prefixed labels** are emitted during **continuous watching**:
  - `[LOCAL ...]` — the event was originated by **this node's local watcher**
    (a local save, delete or rename picked up by watchdog);
  - `[REMOTE ...]` — the event was **caused by a peer**: the master for a
    slave, a slave for the master, or the central server in remote mode.
- **Unprefixed labels** belong to the **reconciliation / full-scan phase**,
  transfers, states and previews (`[DOWNLOAD]`, `[UPLOAD]`, `[IN SYNC]`,
  `[SKIP]`, `[TO ...]`, …) and to `hsync-server`'s own log lines.

The distinction "initial sync vs watching" stays readable at a glance: the
initial reconcile begins with `[INITIAL SYNC]`, then `[DOWNLOAD]`/`[UPLOAD]`
lines follow; `[REMOTE MODIFY]` lines after that mean the full scan finished
and the node is now applying peer events.

> **Known limitation (LAN master).** Origin attribution on the master relies on
> the inbound-origin marker, which has a TTL (`INBOUND_ORIGIN_TTL`, 10 s). If
> the watchdog event fires after the marker expired, the line prints `LOCAL`
> even though the change was peer-caused. The `(CID: ...)` suffix degrades
> together with the prefix (it is absent in the same case), so the line stays
> internally coherent.

## How labels work

- A label is a short, bracketed token: `[DOWNLOAD]`, `[LOCAL CREATE]`,
  `[REMOTE IGNORE DEL]`. Multi-word labels use **spaces** (never underscores).
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
| create | green | additive operations (create, symlink) and positive state transitions (readiness) |
| modify | blue | content changes |
| rename | blue | moves / renames |
| delete | red | destructive operations |
| permission | magenta | permission changes |
| in_sync | dim | no-op (already in sync, skipped) |
| warning | yellow | guards, conflicts, ignored deletions, LAN trust warnings |
| security | red | rejected unsafe paths / hard security refusals |
| infrastructure | magenta | transport-level (WebSocket, echo suppression) |
| phase | white (bold) | lifecycle phase markers (initial sync started) |

## Projects that emit labels

| Code | Project | Notes |
|------|---------|-------|
| **C** | `hsync-client` | CLI; broadest set (server-mode + LAN client/master) |
| **S** | `hsync-server` | REST + WebSocket relay |
| **A** | `hsync-android` | mirrors the full enum; log panel can show any label |
| **D** | `hsync-desktop` | displays the client subprocess logs + a few own markers |

---

## Watching events (prefixed)

Emitted while a node is watching its bucket or applying inbound peer events.
The prefix encodes the **origin** of the event (see the two-level rule above).

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[LOCAL CREATE]` | create | Local watcher: file/directory created (also slave-side dir create, with a `(dir)` suffix, and deferred-create debug lines) | ✓ | | ✓ | ✓ |
| `[LOCAL MODIFY]` | modify | Local watcher: file/directory content modified. The trigger `(closed)`/`(modified)` shows whether it fired from `IN_CLOSE_WRITE` (reliable) or the `on_modified` debounce fallback; `(dir)` marks a directory metadata event (inotify `IN_ATTRIB` on the parent when a child is created/written/renamed/removed) — directory `MODIFY` lines are stat-deduplicated so only genuine mtime changes propagate. A directory `chmod` (mode change, mtime/size unchanged) is NOT logged as `MODIFY`; it is logged `[PERMISSION] mode change: "..." (dir)` (see below) | ✓ | | ✓ | ✓ |
| `[LOCAL RENAME]` | rename | Local watcher: file/directory renamed (also slave-side rename pushed to the master) | ✓ | | ✓ | ✓ |
| `[LOCAL DELETE]` | delete | Local watcher: file/directory deleted (also slave-side delete pushed to the master) | ✓ | | ✓ | ✓ |
| `[LOCAL SYMLINK]` | create | Local watcher: symbolic link created | ✓ | | ✓ | ✓ |
| `[LOCAL IGNORE DEL]` | warning | Local watcher: deletion skipped (ignore-delete / backup mode) | ✓ | | ✓ | ✓ |
| `[LOCAL KEEP]` | in_sync | Local watcher: `.hsynckeep` sentinel created to preserve an empty directory | ✓ | | ✓ | ✓ |
| `[REMOTE CREATE]` | create | Peer-caused: directory created (inbound event applied, or master broadcasting a slave's create) | ✓ | | ✓ | ✓ |
| `[REMOTE MODIFY]` | modify | Peer-caused: file/directory content modified (inbound event applied, or master broadcasting a slave's upload) | ✓ | | ✓ | ✓ |
| `[REMOTE RENAME]` | rename | Peer-caused: file/directory renamed | ✓ | | ✓ | ✓ |
| `[REMOTE DELETE]` | delete | Peer-caused: file/directory deleted | ✓ | | ✓ | ✓ |
| `[REMOTE SYMLINK]` | create | Peer-caused: symbolic link created | ✓ | | ✓ | ✓ |
| `[REMOTE IGNORE DEL]` | warning | Peer-caused: deletion skipped (ignore-delete / backup mode) | ✓ | | ✓ | ✓ |
| `[REMOTE SECURITY]` | security | Peer-caused: unsafe inbound path rejected | ✓ | | ✓ | ✓ |
| `[REMOTE ECHO]` | infrastructure | Peer event echo suppressed (own event discarded) | ✓ | | ✓ | ✓ |
| `[REMOTE DOWNLOAD]` | transfer | Master serving file bytes to a slave | ✓ | | | ✓ |

## Reconciliation, transfers & previews (unprefixed)

Emitted during the full-scan/reconcile phase, by the transfer engine, and by
`hsync-server`'s own request handlers. These never carry an origin prefix.

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[DOWNLOAD]` | transfer | Downloading a file from server / master | ✓ | ✓ | ✓ | ✓ |
| `[UPLOAD]` | upload | Uploading a file to server / master | ✓ | ✓ | ✓ | ✓ |
| `[RESUME]` | transfer | Resuming a partial upload or download | ✓ | | ✓ | ✓ |
| `[MOVE]` | rename | Internal debug trace of a watchdog move, logged *before* the event is classified as rename or delete+create (never the propagated event) | ✓ | | ✓ | ✓ |
| `[DELETE]` | delete | Reconcile-phase deletion (e.g. local file not on master); server delete endpoint | ✓ | ✓ | ✓ | ✓ |
| `[CREATE]` | create | Reconcile-phase directory creation; server event relay | ✓ | ✓ | ✓ | ✓ |
| `[MODIFY]` | modify | Reconcile-phase modification; server event relay | ✓ | ✓ | ✓ | ✓ |
| `[RENAME]` | rename | Reconcile-phase rename; server event relay | ✓ | ✓ | ✓ | ✓ |
| `[PERMISSION]` | permission | Setting file / directory permissions. Includes watcher `mode change` lines: a `chmod` fires only `IN_ATTRIB` (no close), so a file or directory mode-only change is logged `[PERMISSION] mode change: "..."` (with a `(dir)` suffix for directories) instead of `MODIFY` — emitted by the local watcher (file `_process_permission_only`, directory `on_modified` branch) on Remote/LAN-master, and by the LAN slave (`_propagate_dir_permission_change`) | ✓ | | ✓ | ✓ |
| `[SYMLINK]` | create | Reconcile-phase symbolic link creation; server event relay | ✓ | ✓ | ✓ | ✓ |
| `[IN SYNC]` | in_sync | File already in sync (no action required) | ✓ | | ✓ | ✓ |
| `[SKIP]` | in_sync | File skipped | ✓ | | ✓ | ✓ |
| `[CONFLICT]` | warning | File conflict detected (three-way merge) | ✓ | | ✓ | ✓ |
| `[GUARD]` | warning | Mass-deletion guard tripped (deletions paused) | ✓ | | ✓ | ✓ |
| `[TOMBSTONE]` | warning | File deleted remotely while offline; local copy removed | ✓ | | ✓ | ✓ |

### Preview (dry-run)

These appear only with `--preview` / dry-run. They describe what *would*
happen, not what happened.

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[SYNCED]` | in_sync | File is in sync (preview result) | ✓ | | ✓ | ✓ |
| `[TO DOWNLOAD]` | transfer | File would be downloaded | ✓ | | ✓ | ✓ |
| `[TO UPLOAD]` | upload | File would be uploaded | ✓ | | ✓ | ✓ |
| `[TO DELETE]` | delete | File would be deleted | ✓ | | ✓ | ✓ |
| `[TO RENAME]` | rename | File would be renamed | ✓ | | ✓ | ✓ |

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
| `[WATCHER ERROR]` | warning | Local file watcher could not start even with the polling fallback: the kernel inotify limits are exhausted (Errno 24 instances / Errno 28 watches) or descriptors are exhausted | ✓ | | | |
| `[WATCHER FALLBACK]` | warning | File watcher degraded from inotify to polling because an inotify limit was exhausted (higher CPU, ~1 s event latency) | ✓ | | | |
| `[WATCHER RESTORE]` | create | File watcher restored to inotify after the limits freed up | ✓ | | | |
| `[FD EXHAUSTED]` | warning | File-descriptor limit reached (`RLIMIT_NOFILE` / `fs.file-max`): raise the limit or reduce concurrent connections/transfers | ✓ | | | |

## Infrastructure (transport-level)

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[WS]` | infrastructure | WebSocket transport message (e.g. dropping a dead connection) | | ✓ | ✓ | |

## Lifecycle phases

Emitted once per run (or per reconnection) to bracket the startup
synchronization: `[INITIAL SYNC]` marks the beginning of the first full
reconcile, before the per-file transfer lines; the unlabeled
"Initial sync complete" message marks its end, right before the event channel
is established.

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[INITIAL SYNC]` | phase | Initial synchronization started — first full reconcile of a run | ✓ | | | |

## Readiness state

Emitted once per run (or per reconnection/role activation) when the node has
finished its startup sequence and is **actually ready for synchronization**:
the filesystem watcher is active and the event channel (server WebSocket or
LAN master connection) is established. This is the observable "ready" threshold
in the log — the node will now react to file-system events and peer events.

| Label | Category | Description | C | S | A | D |
|-------|----------|-------------|---|---|---|---|
| `[READY]` | create | Node is ready for sync: watcher active + event channel up (remote client, LAN master or LAN slave) | ✓ | | ✓ | ✓ |

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
