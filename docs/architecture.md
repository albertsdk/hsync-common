# HSYNC Common Architecture

This document describes the architecture of `hsync-common`, the shared library
that provides canonical models, constants, and compression utilities for the
HSYNC ecosystem.

> **Note**: Diagrams are written in Mermaid. If they don't render, run `./generate-diagrams.sh` to generate PNG images in the `images/` directory.

## System Overview

```mermaid
graph TB
    subgraph "hsync-common"
        subgraph "Models"
            FILE[File]
            DIR[Dir]
            SYMLINK[Symlink]
            EVENT[Event]
            SYNC[SyncAction]
        end

        subgraph "Utilities"
            COMP[Compression]
            CONST[Constants]
        end
    end

    subgraph "Consumers"
        CLIENT[hsync-client]
        SERVER[hsync-server]
    end

    CLIENT -->|"path dependency"| FILE
    CLIENT -->|"path dependency"| COMP
    CLIENT -->|"path dependency"| CONST
    SERVER -->|"path dependency"| FILE
    SERVER -->|"path dependency"| COMP
    SERVER -->|"path dependency"| CONST
```

## Purpose

Before `hsync-common`, the client and server projects each maintained their own
copies of the data models (`File`, `Dir`, `Symlink`, `Event`, `SyncAction`),
compression logic, and constants. This led to:

- **Code duplication** — ~1 500 lines duplicated across the two projects.
- **Divergence risk** — changes in one project could silently diverge from
  the other, causing protocol incompatibilities.
- **Maintenance overhead** — every fix or improvement had to be applied twice.

`hsync-common` solves these issues by providing a single source of truth.

## Package Structure

```
hsync-common/
├── pyproject.toml              # Poetry configuration
├── README.md
├── docs/
│   └── architecture.md         # This file
└── hsync_common/
    ├── __init__.py
    ├── constants.py             # VERSION, HSYNCKEEP_FILENAME, chunk sizes
    ├── compression.py           # Zstandard compress/decompress utilities
    └── models/
        ├── __init__.py          # Re-exports all models
        ├── file.py              # File model with SHA-256 caching
        ├── dir.py               # Dir model
        ├── symlink.py           # Symlink model
        ├── event.py             # Event + EventName enum
        └── sync_action.py       # SyncAction + SyncActionName enum
```

## Models

### File

The `File` class represents a file with its synchronization metadata:

| Attribute     | Type             | Description                              |
|---------------|------------------|------------------------------------------|
| `filepath`    | `str \| None`    | Full path to the file                    |
| `name`        | `str \| None`    | Base filename (derived from filepath)    |
| `ctime`       | `int \| None`    | Creation time (Unix timestamp)           |
| `mtime`       | `int \| None`    | Modification time (Unix timestamp)       |
| `size`        | `int`            | File size in bytes                       |
| `sha256sum`   | `str \| None`    | SHA-256 checksum of file content         |
| `permissions` | `str \| None`    | Symbolic permission string               |

Key features:
- **SHA-256 caching** — in-memory cache keyed by `(filepath, mtime)` to avoid
  redundant hash computation within a sync cycle.
- **Adaptive chunk sizes** — SHA-256 computation uses 8 KB / 64 KB / 256 KB chunks
  depending on file size for optimal throughput.
- **`FileDict`** — a `TypedDict` for type-safe dictionary serialization.

### Dir

Represents a directory with `path` and `permissions`. Includes `is_hidden_dir()`
to detect dot-prefixed directories.

### Symlink

Represents a symbolic link with `filepath`, `target`, `name`, `ctime`, `mtime`.

### Event / EventName

Represents a file-system synchronization event. `EventName` is a `StrEnum` with
values: `added`, `modified`, `renamed`, `deleted`, `symlink`.

### SyncAction / SyncActionName

Represents a synchronization decision. `SyncActionName` is a `StrEnum` with
values: `download`, `upload`, `delete`, `nothing`.

## Compression

The `compression` module provides Zstandard (zstd) compression with level 3
(good speed/ratio balance):

| Function          | Description                                      |
|-------------------|--------------------------------------------------|
| `compress_data`   | Compress raw bytes                               |
| `decompress_data` | Decompress zstd-compressed bytes                 |
| `compress_file`   | Read and compress a file from disk               |
| `should_compress` | Decide if compression is beneficial (10 KB gate) |

The module also exports `PRECOMPRESSED_EXTENSIONS` — a frozen set of ~80 file
extensions that are already compressed (archives, images, audio, video, etc.).

**Project-specific extensions:**
- `hsync-client` adds upload (32 KB) and LAN (100 KB) thresholds.
- `hsync-server` adds async streaming compression for FastAPI handlers.

## Constants

| Constant             | Value         | Description                              |
|----------------------|---------------|------------------------------------------|
| `VERSION`            | `"1.0.0"`     | HSYNC protocol version (single source)   |
| `HSYNCKEEP_FILENAME` | `".hsynckeep"`| Sentinel file for empty-directory sync   |
| `CHUNK_SIZE_SMALL`   | 8 KB          | SHA-256 chunk size for files < 1 MB      |
| `CHUNK_SIZE_MEDIUM`  | 64 KB         | SHA-256 chunk size for files < 100 MB    |
| `CHUNK_SIZE_LARGE`   | 256 KB        | SHA-256 chunk size for files ≥ 100 MB    |
| `FILE_SIZE_SMALL`    | 1 MB          | Threshold for medium chunk size          |
| `FILE_SIZE_MEDIUM`   | 100 MB        | Threshold for large chunk size           |

## Integration

Both `hsync-client` and `hsync-server` declare a Poetry path dependency:

```toml
hsync-common = { path = "../hsync-common", develop = true }
```

Each project maintains **backward-compatible shim modules** that re-export
symbols from `hsync_common`. For example, in `hsync-client`:

```python
# hsync_client/models/file.py
from hsync_common.models.file import File, FileDict, clear_sha256_cache, ...
```

This ensures that all existing `from hsync_client.models.file import File`
and `from hsync_server.models.file import File` imports continue to work
without any changes to application code or tests.
