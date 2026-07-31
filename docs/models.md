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
- **Adaptive chunk sizes** — SHA-256 computation uses 8 KB / 64 KB / 256 KB
  chunks depending on file size for optimal throughput.

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
values: `download`, `upload`, `delete`, `nothing`.

## TombstoneStore

Records deletion markers so that a peer which was offline at deletion time does
not resurrect a file during a full reconciliation. Key features:

- **Last-writer-wins merge** — `merge()` and `record()` keep the newest timestamp.
- **Privacy-preserving keys** — paths are hashed (SHA-256) before storage.
- **TTL pruning** — `prune()` garbage-collects markers older than 30 days.
- **Untrusted-payload validation** — well-formedness checks prevent hostile peers
  from planting permanent or unbounded deletion markers.
- **JSON persistence** — atomic `save()`/`load()` to the `.hsynctombstones`
  side-car file.

## SyncStateStore / FileVersion

Backs the three-way merge conflict model. `SyncStateStore` persists per-file
base versions (the hash known to both peers) to the `.hsyncstate` side-car so
that conflicts are detected on the next reconciliation rather than by timestamp
alone.

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
