# Utilities

`hsync-common` provides cross-cutting utilities used by all consumers.

## Compression (`hsync_common.compression`)

Zstandard (zstd) compression with level 3:

| Function | Description |
|----------|-------------|
| `compress_data` | Compress raw bytes |
| `decompress_data` | Decompress zstd-compressed bytes (optional hard cap on output size for untrusted payloads) |
| `decompress_stream` | Stream-decompress a zstd byte stream with a hard cap on total output (anti decompression-bomb) |
| `compress_file` | Read and compress a file from disk |
| `should_compress` | Decide if compression is beneficial (10 KB download / 32 KB upload / 100 KB p2p gate) |

The module also exports `PRECOMPRESSED_EXTENSIONS` — a frozen set of 95 file
extensions that are already compressed (archives, images, audio, video, etc.).

Compression support is negotiated between peers during connection setup (see
[Protocol guide](protocol.md)).

## Hashing (`hsync_common.hashing`)

SHA-256 computation with adaptive read chunk sizing (256 KB / 512 KB / 1 MB
depending on file size) and hex digest validation.

## Ignore matcher (`hsync_common.ignore`)

Gitignore-style pattern matching for excluding files from synchronisation.
`IgnoreMatcher` combines three layers:

1. **Default ignore patterns** — built-in patterns for OS cache files
   (`.DS_Store`, `Thumbs.db`, ...) and editor/office temporary files. Always
   active and cannot be disabled.
2. **Per-bucket `.hsyncignore`** — user-defined rules in the bucket root.
3. **Extra patterns** — programmatic patterns (e.g. from CLI `--ignore-pattern`).

## Path validation (`hsync_common.path_validation`)

Safety checks to prevent path manipulation attacks:

| Check | Description |
|-------|-------------|
| Path traversal | Rejects paths containing `../` or absolute paths |
| Null bytes | Rejects paths with embedded null bytes (`\0`) |
| Symlink escape | Validates that resolved symlink targets stay within the allowed directory (`is_safe_symlink_target` — the SSOT used by the client scan/upload guards, the p2p master listing/download, and the server listing/download/WS-event paths) |
| Component validation | Rejects empty path components and reserved names |
| Length limits | Enforces maximum path and filename length limits |

## Permissions (`hsync_common.permissions`)

Octal permission SSOT and remote permission sanitisation. Permissions travel on
the wire as an octal POSIX mode string (e.g. `"644"`, `"755"`), the same model
used by rsync and Syncthing.

**Special bits policy (setuid/setgid/sticky):** these bits are read and
transmitted (a local `setuid` file is reported as `"4755"`), but they are
**never applied** from a remote peer: `"4755"` received on the wire is applied as
`"755"`. This guarantees a synced file can never become a setuid/setgid
executable on a receiving host. For directories, the receiving engine always
keeps owner read/write/execute access (`0o700` floor), so a peer-supplied mode
like `000` cannot lock a device out of its own bucket. See
[ADR-0026](internal/adr/0026-permission-special-bits-policy.md) for the full
rationale and consequences.

## SSL utilities (`hsync_common.ssl_utils`)

Self-signed certificate generation and fingerprint helpers. Used by p2p mode
for persistent master identity.

## Logger (`hsync_common.logger`)

Shared loguru configuration with `BaseInterceptHandler` and log rotation
helpers.

## Clock synchronisation (`hsync_common.clock`)

Clock-offset measurement and correction used to compare file modification times
across devices:

| Function | Description |
|----------|-------------|
| `measure_clock_offset` | NTP-like HTTP round-trip against the server/master `/api/v1/time` endpoint (client-server mode) — the server is the time authority |
| `measure_clock_offset_ntp_multi` | UDP SNTP probe (RFC 4330) against a list of public NTP servers, tried in order until one answers (p2p / no-server startup); the offset is the median of several round-trips |
| `parse_ntp_hosts` | Parses the `HSYNC_NTP_HOSTS` comma-separated host list into raw entries (`host`, `host:port`, `[IPv6]`, `[IPv6]:port`; no validation here) — defaults: `pool.ntp.org`, `time.cloudflare.com`, `time.google.com` |
| `parse_ntp_targets` | Validates each entry through the shared endpoint grammar and returns `(host, port)` targets; malformed entries are dropped and an all-malformed list falls back to the defaults |
| `correct_mtime` | Applies the measured offset to a local modification time (`corrected_mtime = mtime + offset`) |
| `clamp_wire_corrected_mtime` | Clamps a peer-supplied far-future corrected time so no device can win every tie-break |

**Offline/air-gapped behaviour**: when every NTP server is unreachable the
client records offset 0 (raw local time), logs a degraded-temporal-mode notice,
and synchronisation proceeds normally.

The corrected time is carried as `corrected_mtime` inside the version metadata
attached to every file on the wire. When two devices change the same file
concurrently, the most recent corrected time wins the original path and the
other content is preserved as a `_conflicted_copy_` file; if either side lacks
the field the comparison falls back to a deterministic hash tie-break. See the
[Models guide](models.md) and the [conflict model ADR](internal/adr/0023-corrected-mtime-tie-break.md).

## Format (`hsync_common.format`)

Human-readable bytes/duration formatting helpers.

## Env (`hsync_common.env`)

Environment-file loading helpers (`load_env_file`).

## Endpoint (`hsync_common.endpoint`)

Shared `HOST[:PORT]` grammar for every `hsync*` component (`hsync`,
`hsync-bootnode`, `hsync-server`, the desktop GUI and the `HSYNC_*`
environment). `parse_host_port` returns a `HostPort(host, port)`; IPv6 literals
are bracketed in the combined form (`[::1]:443`), and `HostPort.authority`
brackets a bare IPv6 host for URLs/display.

Accepted forms (single source of truth): `host`, `IPv4`, `host:port`,
`IPv4:port`, `[IPv6]`, `[IPv6]:port`; a bare IPv6 literal is a host with no
port. Helpers: `build_https_url`, `parse_https_url`, `build_url` and
`format_authority` produce the canonical HTTPS URL, validate an explicit
`https://…[/path]` URL, and build/bracket `scheme://host:port` composites.

## Runtime (`hsync_common.runtime`)

Runtime environment detection shared across HSYNC projects:

| Function | Description |
|----------|-------------|
| `detect_container` | Detect whether the process runs inside a container (Docker, Podman, Kubernetes, containerd) |
| `is_tty_interactive` | True when both stdin and stdout are attached to a terminal |
| `color_output_enabled` | Whether colored log output should be emitted (respects `--no-color` and `NO_COLOR`) |
| `get_memory_limit_bytes` | Effective RAM limit for this process in bytes (cgroup v2 then v1) |
| `get_cpu_quota_cores` | Effective CPU quota in cores (cgroup v2 then v1) |
| `runtime_summary` | One-line human-readable summary of the runtime environment for startup logs |

## Text (`hsync_common.text`)

Text utilities (e.g. `escape_loguru_braces`).

## Exceptions (`hsync_common.exceptions`)

Shared exception base types (`HSyncError`).

## UPnP-IGD (`hsync_common.upnp`)

Shared, dependency-free SSDP + SOAP client to map a port on the LAN's Internet
Gateway Device. SSRF-hardened because an SSDP reply is unauthenticated data: only
a private LAN source may answer, the `LOCATION` URL must be an `http(s)://`
private IP **literal equal to the reply source**, redirects are refused, and a
`controlURL` cannot change host. Every failure degrades to "no UPnP" (`None` or
`UpnpError`). `discover_igd`, `add_port_mapping`/`delete_port_mapping`,
`build_add_mapping_soap`/`build_delete_mapping_soap`, `parse_soap_error`.
Consumers: `hsync-client` (`UpnpMapper`) and `hsync-bootnode/python`
(`UpnpManager`).

## Rate limiting (`hsync_common.ratelimit`)

`TokenBucketLimiter` — a per-key in-memory token bucket (`capacity` burst,
`refill`/`window` sustained rate, optional `max_keys` LRU ceiling), using a
monotonic clock and never persisting state. `allow`, `has_tokens`, `retry_after`,
`evict_stale`. Consumers: `hsync-client` (P2P listener new-request admission) and
`hsync-bootnode/python` (admission/query/register limits).

## See also

- [Models guide](models.md) — data models reference.
- [Protocol guide](protocol.md) — versioned wire protocol.
- [Internal architecture](internal/architecture.md) — detailed utility reference.
