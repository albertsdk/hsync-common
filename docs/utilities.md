# Utilities

`hsync-common` provides cross-cutting utilities used by all consumers.

## Compression (`hsync_common.compression`)

Zstandard (zstd) compression with level 3:

| Function | Description |
|----------|-------------|
| `compress_data` | Compress raw bytes |
| `decompress_data` | Decompress zstd-compressed bytes (optional hard cap on output size for untrusted payloads) |
| `compress_file` | Read and compress a file from disk |
| `should_compress` | Decide if compression is beneficial (10 KB gate) |

The module also exports `PRECOMPRESSED_EXTENSIONS` — a frozen set of ~80 file
extensions that are already compressed (archives, images, audio, video, etc.).

Compression support is negotiated between peers during connection setup (see
[Protocol guide](protocol.md)).

## Hashing (`hsync_common.hashing`)

SHA-256 computation with adaptive chunk sizing (8 KB / 64 KB / 256 KB depending
on file size) and hex digest validation.

## Ignore matcher (`hsync_common.ignore`)

Gitignore-style pattern matching for excluding files from synchronisation.
`IgnoreMatcher` combines three layers:

1. **Default ignore patterns** — built-in patterns for OS cache files
   (`.DS_Store`, `Thumbs.db`, ...) and editor/office temporary files. Always
   active and cannot be disabled.
2. **Per-bucket `.hsyncignore`** — user-defined rules in the bucket root.
3. **Extra patterns** — programmatic patterns (e.g. from CLI `--ignore-patterns`).

## Path validation (`hsync_common.path_validation`)

Safety checks to prevent path manipulation attacks:

| Check | Description |
|-------|-------------|
| Path traversal | Rejects paths containing `../` or absolute paths |
| Null bytes | Rejects paths with embedded null bytes (`\0`) |
| Symlink escape | Validates that resolved symlink targets stay within the allowed directory |
| Component validation | Rejects empty path components and reserved names |
| Length limits | Enforces maximum path and filename length limits |

## Permissions (`hsync_common.permissions`)

Octal permission SSOT and remote permission sanitisation. Setuid/setgid/sticky
bits are stripped from peer-supplied permission strings.

## SSL utilities (`hsync_common.ssl_utils`)

Self-signed certificate generation and fingerprint helpers. Used by LAN mode
for persistent master identity.

## Logger (`hsync_common.logger`)

Shared loguru configuration with `BaseInterceptHandler` and log rotation
helpers.

## Clock (`hsync_common.clock`)

NTP-style clock offset computation for client-server time synchronisation.

## Format (`hsync_common.format`)

Human-readable bytes/duration formatting helpers.

## Env (`hsync_common.env`)

Environment-file loading helpers.

## Text (`hsync_common.text`)

Text utilities (e.g. `escape_loguru_braces`).

## Exceptions (`hsync_common.exceptions`)

Shared exception base types (`HSyncError`).

## See also

- [Models guide](models.md) — data models reference.
- [Protocol guide](protocol.md) — versioned wire protocol.
- [Internal architecture](internal/architecture.md) — detailed utility reference.
