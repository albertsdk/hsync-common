# Data Models

`hsync-common` defines the canonical data models shared across all HSYNC
consumers. These models are the single source of truth for the wire format.

## File

Represents a file with its synchronisation metadata:

| Attribute | Type | Description |
|-----------|------|-------------|
| `filepath` | `str \| None` | Full path to the file |
| `name` | `str \| None` | Base filename (derived from filepath) |
| `ctime` | `int \| None` | Creation time (Unix timestamp) |
| `mtime` | `int \| None` | Modification time (Unix timestamp) |
| `size` | `int` | File size in bytes |
| `sha256sum` | `str \| None` | SHA-256 checksum of file content |
| `permissions` | `str \| None` | Octal permission string (e.g. `"644"`) |

Key features:
- **SHA-256 caching** — in-memory cache keyed by `(filepath, mtime)` to avoid
  redundant hash computation within a sync cycle.
- **Version metadata** — `version` carries the vector-clock state and the
  clock-offset-corrected `corrected_mtime` used by the chronological
  tie-break on concurrent edits (see `SyncStateStore` below).
- **Adaptive chunk sizes** — SHA-256 computation and transfer reads use
  256 KB / 512 KB / 1 MB chunks depending on file size. The sub-1MB tier is
  sized so a typical burst file is read in one iteration; measured on the HTTPS
  apply path, an 8 KB tier cost 5.5 ms CPU/file against 4.3 ms at 256 KB.

## Dir

Represents a directory with `path` and `permissions`. Includes `is_hidden_dir()`
which delegates to the active `IgnoreMatcher` to check whether a directory
should be excluded from synchronisation.

## Symlink

Represents a symbolic link with `filepath`, `target`, `name`, `ctime`, `mtime`.

## Event / EventName

Represents a file-system synchronisation event. `EventName` is a `StrEnum` with
values: `added`, `modified`, `renamed`, `deleted`, `symlink`.

## SyncAction / SyncActionName

Represents a synchronisation decision. `SyncActionName` is a `StrEnum` with
values: `download`, `upload`, `delete`, `delete_remote`, `upload_symlink`,
`download_symlink`, `nothing`.

The two symlink actions replicate the link structurally (the path and target
pair) — never the target's file content.

`to_dict()` serializes `file`, `name`, `timedelta`, the `conflict` flag
(`True` when the action overwrites a locally-modified file whose local copy
should be preserved first), and `tombstone_confirmed` (`True` when a local
delete is backed by a matching deletion marker, so the mass-deletion guard
can treat it as intentional).

## TombstoneStore

Records deletion markers so that a peer which was offline at deletion time does
not resurrect a file during a full reconciliation. Tombstones are **not** a
recycle bin: they prevent resurrection, they do not store file contents and
they do not provide restore.

Key features:

- **Causal merge** — `merge()` and `record()` follow vector-clock dominance.
  Concurrent markers use a deterministic content-based tie-break (content hash,
  then version id, then author). The wall-clock timestamp never decides the
  merge; it is used only for TTL garbage collection and anti-poisoning checks.
- **Privacy-preserving keys** — paths are hashed (SHA-256) before storage.
- **TTL pruning** — `prune()` garbage-collects markers older than 90 days.
  That window is a storage bound only; correctness does not depend on it.
- **Untrusted-payload validation** — well-formedness checks prevent hostile peers
  from planting permanent or unbounded deletion markers.
- **SQLite persistence** — `save()`/`load()` against the per-folder SQLite DB
  (`<device_dir>/syncstate/<uuid>.db`), keyed by folder UUID (`.hsyncfolder`).

## TrashEntry

The record of one deletion this device applied, kept so the bytes can be
restored (ADR-0056). It is **not** a wire model: the deletion itself still
travels as a tombstone, and the entry never leaves the device.

Layout, under the trash root (`<state dir>/trash`, relocatable with
`HSYNC_TRASH_DIR` or the client's `--trash-dir`):

```text
<folder id>/<entry id>/entry.json          the record
<folder id>/<entry id>/payload/<relpath>   the deleted bytes
```

`entry.json` holds `relpath` (bucket-relative, POSIX separators), `sha256` and
`size` of the bytes, `mtime_ns` and `mode` to restore the metadata,
`deleted_at`, `origin` (`sync` when a cycle applied the deletion, `user` when a
front-end removed the file), the authoring `cid` and the `bucket` name.

- **Validated on read** — `parse_trash_entry` treats a damaged or hand-edited
  entry as absent, and `is_safe_relpath` refuses absolute paths, `..`
  components, drive letters and backslashes, so no entry can reach outside the
  store.
- **Integrity before restore** — the recorded `sha256` is checked against the
  stored copy; a mismatch reports `payload-corrupt` instead of restoring bytes
  that are not the ones deleted.
- **Bounded** — a retention window (30 days by default) and a size budget
  (`TRASH_RETENTION_DAYS_DEFAULT`, `TRASH_QUOTA_PERCENT_DEFAULT`,
  `TRASH_QUOTA_FLOOR_MB_DEFAULT` in `hsync_common/defaults.py`) are storage
  bounds only: correctness never depends on them.

The store implementation and the `hsync trash` commands live in `hsync-client`
(`hsync_client/trash.py`), which is also what a front-end reads through
`hsync trash list --json`.

## HistoryEntry

The record of one blob the **server** replaced or removed, kept so an overwrite or
a deletion stays recoverable for a window (ADR-0057). It is not a wire model: no
peer sees it and the protocol is unchanged.

Layout, under the history root (`<state dir>/history`):

```text
<bucket>/<entry id>/entry.json          the record
<bucket>/<entry id>/payload/<relpath>   the preserved bytes
```

`entry.json` holds `relpath` (bucket-relative, POSIX separators), `sha256` and
`size` of the bytes, `mtime_ns` and `mode` to restore the metadata,
`recorded_at`, `reason` (`overwrite` or `delete`), the `cid` that caused it and
the `bucket` name.

- **Distinct from `TrashEntry`** — a replaced blob is not a deletion, so the record
  carries `reason` instead of `origin`; the layout and the safety helpers
  (`is_safe_relpath`, `is_safe_entry_id`) are shared.
- **Validated on read** — `parse_history_entry` treats a damaged or hand-edited
  record as absent; an unknown `reason` is refused.
- **Bounded** — `HISTORY_RETENTION_DAYS_DEFAULT` (7 days) and the quota set by
  `HISTORY_QUOTA_PERCENT_DEFAULT` / `HISTORY_QUOTA_FLOOR_MB_DEFAULT`
  (`hsync_common/defaults.py`) are storage bounds only.

The store, the overwrite/delete hooks and the `hsync-server admin history`
commands live in `hsync-server`.

## SyncStateStore / FileVersion

Backs the causal three-way merge (vector-clock) conflict model. `SyncStateStore`
persists per-file versions in the per-folder SQLite DB (keyed by the
`.hsyncfolder` UUID); each `FileVersion`
records the base content hash, the causal `vclock`, and a `corrected_mtime`
(the local modification time corrected by the clock offset measured against
the server or the NTP servers — see the [Clock section](utilities.md#clock-synchronisation-hsync_commonclock)).
When two devices edit the same file concurrently, the version with the most
recent corrected time keeps the original path and the losing content is
preserved as a `_conflicted_copy_` file; when a side lacks the field the
comparison falls back to a deterministic hash tie-break.

## Delta transfer models

Wire models for rsync-style block-level sync:

| Model | Purpose |
|-------|---------|
| `BlockSignature` | Signature of a single base-file block (index, offset, length, weak Adler32, strong SHA-256) |
| `DeltaOp` | Reconstruction operation (copy from base or data from literal payload) |
| `DeltaInstructions` | Ordered operations to rebuild the new file from base + literals |
| `DeltaApplyMetadata` | Metadata for delta upload (cid, base/new SHA-256, block size, ops, …) |

## See also

- [Utilities guide](utilities.md) — compression, hashing, ignore, path validation.
- [Protocol guide](protocol.md) — handshake, capabilities, p2p election, pairing.
- [Internal architecture](internal/architecture.md) — detailed model reference.
