# ADR 0021 — Server-side conflicted copy on concurrent upload

- **Status:** Proposed
- **Date:** 2026-08-11

## Context

[ADR-0006](0006-master-authoritative-conflict-model.md) defines a master-
authoritative conflict model where, on genuine divergence, the remote (master)
wins but the **local** content is preserved as `.conflict-<host>-<timestamp>`.
The client implements this via `hsync_client.sync_state` (three-way merge) and
the `resolve_three_way` function in `hsync_common.models.version`.

However, the **server** (`hsync_server/api/files/upload.py`) has no conflicted-
copy mechanism at all. When two clients upload different content for the same
file path, the last writer overwrites the earlier one silently. A `.backup` file
is created during the upload window but deleted on success. This means:

- A client that uploaded its version, then goes offline, and another client
  uploads a different version — the first client's version is **lost forever**
  with no trace.
- The server has no way to signal to any client that a conflict occurred.

This gap was identified during the 2026-08-11 test audit of `hsync-server`.

## Decision

We will implement **server-side conflicted copies (Dropbox-style)**:

- When an upload would overwrite an existing file with **different content**
  (different SHA-256), the server renames the existing file to:
  ```
  <filename>_conflicted_copy_<ISO8601>_<cid>.<ext>
  ```
- The backup file (already created at `upload.py:267`) is repurposed for this:
  instead of being deleted on success, it is renamed to the conflicted copy name.
- The new content is then written atomically to the original path (unchanged
  from current behaviour).
- No changes to the wire protocol, no new form fields, no client modifications
  required.
- The conflicted copy appears in the bucket listing and is synced to all peers
  on their next reconciliation — every peer sees both versions.

### Why not Option B (expected_mtime conflict detection)?

- `mtime` is unreliable across devices (clock skew, FAT32 2-second granularity).
- Requires client-side changes to send `expected_mtime` and handle 409 responses.
- Adds a decision point for the client (force overwrite vs. download remote),
  which introduces user-facing complexity.

### Why not Option D (vector clocks / CRDT)?

- Disproportionate complexity for the current scale and trust model of HSYNC.
- ADR-0006 already rejects CRDT in favour of master-authoritative.

### Why Dropbox-style conflicted copies?

- Zero changes to the wire protocol or client code.
- Both versions survive automatically — no silent data loss.
- Industry standard: Dropbox, Syncthing, Nextcloud all use this pattern.
- The conflicted copy is visible to all peers via normal file listing and sync.

## Consequences

- The server may accumulate conflicted copies over time. Cleanup is manual
  (the user deletes the conflicted copy when they've resolved it) — same as
  Dropbox and Syncthing.
- Conflicted copies are regular files: they are listed, downloaded, and synced
  like any other file. A future enhancement could exclude them from the sync
  listing or flag them with a special attribute.
- The existing `.backup` mechanism is repurposed rather than duplicated.
- No change to `get_sync_actions()` on the client: the conflicted copy is a new
  file with a different name, so the sync engine treats it as a new file to
  download — which is the desired behaviour (all peers eventually see both
  versions).

## Related

- [ADR-0006](0006-master-authoritative-conflict-model.md) — Client-side conflict model
- `hsync_server/api/files/upload.py:262-267` — Backup creation (now repurposed for conflicted copies)
- `hsync_server/api/files/upload.py:451-476` — Conflicted copy logic (new)
- `hsync-common/tests/test_version.py` — Three-way merge tests
