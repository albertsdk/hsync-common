# ADR 0056 — Sync trash with causal restore

- **Status:** Accepted
- **Date:** 2026-11-24

## Context

A deletion applied by the engine is a hard `unlink`:
`hsync_client/sync.py::_apply_deletions` removes the local copy and records a
causal deletion marker (ADR-0003). Nothing survives the call, and the product
offers no restore path (`hsync-client/docs/conflict-resolution.md`). The
confirmation dialog in `hsync-desktop` is therefore the only human gate on an
irreversible operation, which pushes the front-end towards confirming more than
it should (the routine, non-destructive plan included).

Deletions themselves are already causal and correct: a tombstone proves the
removal is intentional, so an offline peer does not resurrect the file, and a
path re-created after the deletion mints a clock that supersedes the marker
(delete-vs-recreate, ADR-0003). What is missing is a place for the **bytes**.

Two mechanisms were considered:

| Alternative | Rejected because |
|-------------|------------------|
| Hand deletions to the OS recycle bin / trash | No restore contract: restoring from the OS recreates the file while the tombstone is still authoritative, so the next cycle deletes it again. It also has no answer on a NAS (WD OS5, systemd service) and cannot be verified by a black-box test |
| Versioned object store (keep every revision) | Multiplies storage for every edit, not only for deletions, and duplicates what the filesystem/backup layer already offers |
| Front-end-only trash | Each front-end would re-implement move/restore/prune, and the deletion policy would differ between CLI, desktop, NAS and Android |
| **Device-local trash with a causal restore (chosen)** | One implementation, no wire change, works headless, testable black-box |

## Decision

A deletion applied by the engine **moves the bytes** into a device-local trash
store instead of unlinking them, and a restore is a plain file write that the
causal model resolves.

* **Location**: under the installation state dir (ADR-0025), never inside the
  synced folder — `<trash root>/<folder id>/<entry id>/`, with `entry.json` and
  `payload/<relpath>`. `HSYNC_TRASH_DIR` relocates the root. Keeping the store
  outside the folder is what leaves the wire protocol untouched: no peer sees
  the trash, no ignore rule has to hide it and no client has to learn a new
  frame.
* **No protocol change**: the deletion is still advertised as a tombstone. The
  trash changes *how* this device disposes of the bytes, never *what* is
  deleted, so convergence, the mass-deletion guard (ADR-0015) and the causal
  model are unaffected.
* **Restore is causally a re-create**: the engine writes the file back and the
  existing rule does the rest — a scanned local version whose clock supersedes
  the marker is uploaded, and every peer resurrects the path. No state-DB
  surgery, no second writer, no instance lock.
* **Hot by construction**: because neither `list` nor `restore` touches the
  per-folder state DB, both work while a sync runs. The single-writer
  discipline of the state DB (ADR-0025) is preserved rather than bent.
* **Bounds**: a retention window (30 days by default, the industry default for
  a service-side trash) and a size budget — a share of the filesystem hosting
  the trash with a floor, overridable explicitly. Retention and budget are
  storage GC only; correctness never depends on them.
* **Degradation is reported, never silent**: if the move into the store fails
  (unwritable volume, `ENOSPC`, cross-device copy error), the cycle logs the
  loss and still deletes, because blocking the deletion would make the file
  reappear on every cycle. The alternative — aborting the deletion — converts a
  storage failure into a permanent sync loop.

## Consequences

* The trash is **per device**: a reinstall or a device migration loses it, and
  it is not shared between peers. Restoring on device A does not put the bytes
  on device B's trash.
* `--trash-max-size`/retention bound the store per installation (one budget
  across folders), so N shares cannot each fill the same volume.
* Symlinks and special files are still deleted outright: their "content" is a
  target outside the store, and moving the link would preserve nothing the user
  can recover.
* Front-ends get one contract instead of the layout: `hsync trash list --json`
  returns `[{entry_id, path, size, deleted_at, origin, cid, bucket}]`, the shape
  the desktop and Android mirror. Front-ends also inherit the guards (an entry
  whose destination exists is never overwritten, a `download-only` folder
  refuses the restore); the desktop's system-trash action is subsumed, since a
  delete that bypasses the store has no coherent restore.
* Follow-up obligations: man page, `docs/configuration.md`, the WD OS5 web UI
  (`trash.php`) and the Android mirror read the same `TrashEntry` shape; a
  restore into a `download-only` folder must be refused (the mirror rule would
  delete it again).
