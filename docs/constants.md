# Constants

`hsync-common` defines the canonical constants shared by all HSYNC consumers.
They are imported from `hsync_common.constants` and are the single source of
truth for the protocol version, sentinel filenames, chunk sizes, and delta
transfer thresholds.

## Application, protocol & wire headers

| Constant | Value | Description |
|----------|-------|-------------|
| `HSYNC_VERSION` | `"1.0.0"` | HSYNC application version — single source of truth, shared by client, server, desktop and Android. |
| `HEADER_CLIENT_NAME` | `"X-Client-Name"` | REST header identifying the client product (`hsync-client`, `hsync-android`). |
| `HEADER_CLIENT_VERSION` | `"X-Client-Version"` | REST header carrying the client's application version. |
| `HEADER_SERVER_VERSION` | `"X-Server-Version"` | REST header carrying the server's application version. |
| `HEADER_PROTOCOL_VERSION` | `"X-Protocol-Version"` | REST header carrying the wire-protocol version on every request and response. |
| `HEADER_CHECKSUM_SHA256` | `"X-Checksum-SHA256"` | Canonical response checksum header for full-file downloads from a server, LAN master, or seeder. |
| `CLIENT_NAME_PATTERN` / `is_valid_client_name` | `^[a-z][a-z0-9-]*[a-z0-9]$` | Shape a `X-Client-Name` value must satisfy (`hsync-client`, `hsync-android`); the server rejects anything else with 400. |
| `CONTENT_TYPE_OCTET_STREAM` | `"application/octet-stream"` | Wire media type for file/literal payloads, shared by client, server and Android. |
| `CONTENT_TYPE_JSON` | `"application/json"` | Wire media type for JSON responses, shared by client, server and Android. |
| `WS_MAX_MESSAGE_BYTES` | `2 MiB` | Maximum WebSocket text-frame size accepted (auth, event, and LAN inventory frames); also the LAN source-body ceiling. |

## Sentinel & Side-car filenames

| Constant | Value | Description |
|----------|-------|-------------|
| `HSYNCKEEP_FILENAME` | `".hsynckeep"` | Sentinel file placed in empty directories to force sync of the directory structure (like `.gitkeep`). Always preserved regardless of ignore rules. |
| `HSYNCIGNORE_FILENAME` | `".hsyncignore"` | Per-bucket gitignore-style ignore file. |
| `HSYNCFOLDER_FILENAME` | `".hsyncfolder"` | Folder-identity marker (UUIDv4) at the bucket root. |
| `SYNCSTATE_DB_FILENAME` | `"syncstate.db"` | Installation-level causal-state database (outside the bucket). |
| `HSYNC_STATE_DIR_ENV` | `"HSYNC_STATE_DIR"` | Environment override for the state directory that holds `syncstate.db`. |
| `HSYNCTOMBSTONES_FILENAME` | `".hsynctombstones"` | Legacy name; rejected on the wire, no longer written. |
| `HSYNCSTATE_FILENAME` | `".hsyncstate"` | Legacy name; rejected on the wire, no longer written. |

## Partial transfer artifacts

| Constant | Value | Description |
|----------|-------|-------------|
| `PARTIAL_DOWNLOAD_SUFFIX` | `".part"` | Suffix for in-progress download targets. File is atomically renamed after checksum verification. |
| `PARTIAL_DELTA_SUFFIX` | `".delta.part"` | Suffix for in-progress delta reconstruction targets. |

## Hashing — chunk sizes

Adaptive chunk sizing for SHA-256 computation based on file size:

| Constant | Value | Applies to |
|----------|-------|------------|
| `CHUNK_SIZE_SMALL` | 8 KB | Files < 1 MB |
| `CHUNK_SIZE_MEDIUM` | 64 KB | Files ≥ 1 MB and < 100 MB |
| `CHUNK_SIZE_LARGE` | 256 KB | Files ≥ 100 MB |

| Constant | Value | Description |
|----------|-------|-------------|
| `FILE_SIZE_SMALL` | 1 MB | Threshold for medium chunk size |
| `FILE_SIZE_MEDIUM` | 100 MB | Threshold for large chunk size |

## Delta transfer (rsync-style)

Throttling controls for block-level delta synchronisation. See
[Delta transfer](delta.md) for the algorithm overview.

### Block-size selection

Adaptive block sizes selected by base-file size:

| Constant | Value | Applies to |
|----------|-------|------------|
| `DELTA_BLOCK_SIZE_SMALL` | 4 KB | Files < 1 MB |
| `DELTA_BLOCK_SIZE_MEDIUM` | 16 KB | Files 1–10 MB |
| `DELTA_BLOCK_SIZE_LARGE` | 64 KB | Files 10–100 MB |
| `DELTA_BLOCK_SIZE_XLARGE` | 256 KB | Files > 100 MB |

### Eligibility thresholds

| Constant | Value | Description |
|----------|-------|-------------|
| `DELTA_MIN_FILE_SIZE` | 256 KB | Minimum file size to attempt delta sync (remote/server mode). |
| `DELTA_MIN_FILE_SIZE_LAN` | 1 MB | Minimum file size for LAN delta sync (higher threshold for NAS ARM devices). |
| `DELTA_MAX_CHANGE_RATIO` | 0.50 (50%) | Maximum fraction of changed base blocks for delta to stay worthwhile. Above this the sender falls back to a full transfer. |
| `DELTA_MAX_LITERAL_SIZE` | 1 GB | Hard cap on the literal payload produced by a single delta. |

### Security & expiry

| Constant | Value | Description |
|----------|-------|-------------|
| `DELTA_TOKEN_TTL` | 300 s (5 min) | Time-to-live of a server-issued literal-payload download token (single-use). |
| `DELTA_MAX_SIGNATURES` | 100 000 | Maximum number of block signatures in an exchange. |
| `DELTA_MAX_OPS` | 100 000 | Maximum number of operations in a delta-instructions payload. |
| `DELTA_TOCTOU_REHASH_THRESHOLD` | 10 MB | Files smaller than this get a full SHA-256 re-hash after the rolling scan to detect TOCTOU content changes missed by mtime+size. |

## Default ignore patterns

`DEFAULT_IGNORE_PATTERNS` is a tuple of built-in gitignore-style patterns always
active in `IgnoreMatcher`. See [Ignore file](ignore-file.md) for the full list
and rationale.

## See also

- [Usage](usage.md) — how to import and use the library.
- [Ignore file](ignore-file.md) — `.hsyncignore` syntax and API reference.
- [Delta transfer](delta.md) — rsync-style block-level sync algorithm.
- [Models guide](models.md) — data models reference.
