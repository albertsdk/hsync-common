# ADR 0057 — Server history: the bytes a write replaces or a delete removes

- **Status:** Accepted
- **Date:** 2026-11-24

## Context

The server keeps exactly **one blob per path**. `hsync_server/api/files/upload.py`
snapshots the previous content to `<path>.backup` for the length of the publish
and removes it afterwards, and `hsync_server/maintenance.py::delete_path_state`
unlinks the last copy after writing the causal tombstone. Once a cycle completes,
the previous content is gone and only the client keeps a copy — and the client's
trash (ADR-0056) cannot help with an **overwrite**: the peer that produced the new
version already holds it as its own current state, so "restore" on that peer means
"write the old bytes back", not "revert a deletion".

That leaves one gap the product has no answer for: a wrong or corrupted upload
that the server accepted destroys the only server-side copy of the previous
content, and a deletion destroys the only server-side copy of the file.

## Decision

Keep the bytes the server replaces or removes in a **per-bucket history store**
under the installation state dir, for a retention window:

```text
<state dir>/history/<bucket>/<entry id>/{entry.json,payload/<relpath>}
```

- **Outside every served bucket**, so no peer sees it, no ignore rule hides it,
  and the wire protocol is unchanged — the same stance as ADR-0056.
- **A distinct entity from the trash**, not a re-use of it: an overwrite is not a
  deletion. The record is `HistoryEntry`
  (`hsync_common/models/history.py::HistoryEntry`) with `reason`
  (`overwrite` | `delete`) where the trash has `origin`, and `recorded_at` where
  the trash has `deleted_at`. The **layout and the path-safety helpers** are
  shared; the identity is not. This mirrors how the field separates the two
  concepts: object stores keep a *version* and a *delete marker* apart, and
  Nextcloud ships `files_versions` next to `files_trashbin` rather than folding
  one into the other.
- **On by default** (`HISTORY_RETENTION_DAYS_DEFAULT` = 7 days): an overwrite the
  server accepted is already committed on the peer, so the window is the only way
  back. The store is bounded like the trash — a share of the hosting filesystem
  set by `HISTORY_QUOTA_PERCENT_DEFAULT` with `HISTORY_QUOTA_FLOOR_MB_DEFAULT` as
  a floor — and `0` disables it for operators who do not want the space cost.

## Consequences

- Storage: a replaced blob is duplicated once per overwrite inside the window, so
  a hot path (a log file rewritten every minute) costs more; the size budget, not
  the age, is what bounds that.
- The `.backup` transient keeps its current role (readers keep a complete copy
  while the publish runs); the history entry is the durable one, and the two must
  not be confused when the sweep reclaims an orphaned snapshot.
- A restore writes the bytes back into the bucket. The server is then the author
  of a new version, which must supersede the tombstone the deletion recorded —
  this is the invariant the implementation tests first, not last
  (`hsync-server/hsync_server/maintenance.py::restore_entry`). The new version's
  clock merges the marker's clock and any surviving version clock and is ticked
  under the server's cid, so the restore is causally *after* the deletion instead
  of racing it, and a peer whose state still carries the marker sees an ancestor
  and concedes on its next cycle.
- A restore keeps the entry: retention, not the restore, decides when the copy
  goes away, so a wrong restore is itself undoable. It refuses an occupied path
  unless `--overwrite` is asked (which captures the replaced content first), and
  it refuses to publish a payload whose size or SHA-256 no longer matches the
  record — the store may be hardlinked, so an external writer editing the
  original in place is exactly the case that check exists for.
- No new wire contract: the admin CLI's `--json` listing is the only surface a
  front-end reads, and it carries the same fields plus `reason`. `history
  restore` mutates the bucket, so it also mutates the causal state above; it
  broadcasts no live event, and every connected client picks the path up on its
  next cycle.
