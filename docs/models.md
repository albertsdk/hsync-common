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
- **SQLite persistence** — `save()`/`load()` against the installation
  `syncstate.db`, keyed by folder UUID (`.hsyncfolder`).

## SyncStateStore / FileVersion

Backs the causal three-way merge (vector-clock) conflict model. `SyncStateStore`
persists per-file versions in the installation `syncstate.db` (keyed by the
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
- [Protocol guide](protocol.md) — handshake, capabilities, LAN election, pairing.
- [Internal architecture](internal/architecture.md) — detailed model reference.
