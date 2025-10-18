# HSYNC Common Library — Cross-cutting utilities

Leaf helpers shared by every project. Check here before writing any new
formatting/hashing/parsing helper (DRY rule in `CLAUDE.md`).

## constants.py

- `HSYNC_VERSION = "1.0.0"` (`constants.py:24`) — ecosystem version SSOT.
- Wire headers `HEADER_CLIENT_NAME/CLIENT_VERSION/SERVER_VERSION/PROTOCOL_VERSION`
  (`constants.py:33`) — REST header names shared by client, server and the
  Android mirror; `CLIENT_NAME_PATTERN` (`:43`) + `is_valid_client_name`
  (`:48`) validate the slug shape and are the same rule the server middleware
  applies to `X-Client-Name`.
- Wire content types `CONTENT_TYPE_OCTET_STREAM` / `CONTENT_TYPE_JSON`
  (`constants.py:63`) — media types shared by the Python client/server and the
  Kotlin mirrors.
- Sentinel / engine filenames: `.hsynckeep` (`:43`), `.hsyncignore` (`:48`),
  `.hsyncfolder` (`:106`), `syncstate.db` (`:111`), `HSYNC_STATE_DIR` (`:115`);
  leftover `.hsynctombstones` / `.hsyncstate` (`:120`/`:121`) stay rejected
  on the wire (ADR-0025).
- Adaptive chunk tiers: `CHUNK_SIZE_SMALL/MEDIUM/LARGE` (`:128`–`:130`) gated by
  `FILE_SIZE_SMALL/MEDIUM` (`:133`/`:134`).
- `PARTIAL_DOWNLOAD_SUFFIX = ".part"` (`:144`).

## hashing.py

- `is_sha256_hex` (`hashing.py:31`): wire-facing digest-shape gate — required
  before `hmac.compare_digest` (raises `TypeError` on non-ASCII input).
- `adaptive_chunk_size` (`hashing.py:46`) picks a tier from file size.
- `compute_sha256` (`hashing.py:67`) + async `compute_sha256_async`
  (`hashing.py:84`).

## delta/rolling_checksum.py

- `compute_signatures(filepath, block_size)` (streamed, bounded memory) and
  `signatures_for_data(data, block_size)` (in-memory twin for fixture/test
  builders) share the same per-chunk weak+strong helper, so the two paths
  cannot drift.

## compression.py (Zstandard, level 3)

- `should_compress` (`compression.py:170`) — size/extension gate.
- `compress_data`/`decompress_data` (`:217`/`:222`), `compress_file` (`:307`).
- `decompress_data(data, max_output_size=...)` enforces a hard cap on the
  decompressed size via a capped streaming read — mandatory for wire-supplied
  payloads (anti decompression-bomb). `decompress_stream` (`:258`) is the
  streaming variant for HTTP response bodies (yields capped chunks).
- Thresholds: `MIN_SIZE_FOR_COMPRESSION` 10 KB (`:35`), download (`:38`), upload
  32 KB (`:43`), LAN 100 KB (`:48`); `PRECOMPRESSED_EXTENSIONS` frozenset (`:57`);
  encoding token `CONTENT_ENCODING_ZSTD` (`:26`).

## permissions.py (octal SSOT)

- `mode_to_octal` (`permissions.py:34`), `octal_to_mode` (`:47`),
  `is_valid_octal_permissions` (`:59`), `get_permissions` (`:97`);
  `PERMISSION_MASK = 0o7777` (`:24`). Used by `File`/`Dir` and the server upload
  form.
- Wire-facing: `REMOTE_PERMISSION_MASK = 0o777` (`:31`) and
  `sanitize_remote_permissions` (`:74`) strip setuid/setgid/sticky bits from
  peer-supplied permission strings before they are applied locally.

## path_validation.py

- Char/name guards: `has_forbidden_chars` (`:118`), `has_control_chars` (`:123`),
  `is_reserved_name` (`:128`), `has_problematic_trailing` (`:139`).
- `is_valid_filename` (`:144`), traversal guards `has_dotdot_component` (`:181`),
  `is_safe_path_component` (`:200`), `is_valid_path` (`:232`),
  `safe_resolve_path` (`:344`).
- Bucket names: `BUCKET_NAME_PATTERN` (`:319`), `is_valid_bucket_name` (`:324`).
- `sanitize_filename` (`:261`).
- Wire-facing remote-path validation (`:380`+): `INTERNAL_FILENAMES`
  (`.hsyncignore`/`.hsyncfolder`/legacy `.hsyncstate`/`.hsynctombstones`), `is_internal_name`
  (also matches `*.part`; comparison is case-insensitive so case variants
  like `.HSYNCIGNORE`/`x.PART` are rejected on case-insensitive
  filesystems), `validate_remote_relpath` (rejects `..`, absolute
  paths, drive letters, `\`, forbidden/control chars, reserved names,
  problematic trailing chars, internal artifacts), `resolve_within`
  (validation + `resolve()`/`relative_to()` confinement; new
  `resolve_final=False` kwarg: the final component is NOT dereferenced, so
  delete/replace/symlink-materialisation operate on the LINK entry — a
  dangling link is a real directory entry and must be removable, while
  intermediate directory symlinks stay confined),
  `wire_symlink_target` (rsync `munge` semantics: an ABSOLUTE in-bucket
  target is converted to a path relative to the link's directory for wire
  replication — the sender's filesystem layout must never reach peers;
  escaping targets return `None`),
  `is_safe_symlink_target` (SSOT, shared with the server). Every component
  that can dereference a local path (client scan `sync.get_files_local`,
  client upload `transfer.upload_file`, LAN master listing/download
  `lan_server`, server listing/download `api/files/*`, WS event handlers)
  uses it to refuse symlinks whose target escapes the bucket.
- Event-payload path keys: `WIRE_PATH_KEYS` + `wire_relpaths` (`:435`) —
  SSOT for the set of path-carrying keys (`filepath`, `path`) used by both
  the server relay gate and the client dispatcher.

## ignore.py (.hsyncignore matcher)

- `IgnoreMatcher` (`ignore.py:41`, pathspec-backed). Process-global active
  matcher: `set_active_matcher` (`:163`), `get_active_matcher` (`:176`),
  `should_skip` (`:182`). `.part` files and `INTERNAL_FILENAMES` are always
  excluded. `_to_relative` strips only a
  leading `./`, so user patterns can match dotfiles.

## ssl_utils.py (LAN TLS identity)

- `generate_rsa_private_key` (`:32`, `DEFAULT_KEY_SIZE = 2048` `:29`),
  `build_self_signed_certificate` (`:37`).
- Serialization: PEM cert/key (`:85`/`:90`), unencrypted PKCS#8
  `serialize_private_key_unencrypted` (`:106`).
- Fingerprints: `compute_cert_fingerprint` (`:124`), `verify_cert_fingerprint`
  (`:130`), `get_server_cert_fingerprint` (`:136`). Underpins TOFU pinning.

## logger.py

- `BaseInterceptHandler` (`logger.py:86`) routes stdlib logging into loguru with
  markup escaping. `LEVEL_STYLES` (`:40`); rotation defaults (`:54`–`:63`),
  `get_rotation_config` (`:66`); `build_record_formatter` (`:147`);
  `configure_handlers` (`:200`).

## labels.py (action-label & colorization SSOT)

Single source of truth for the bracketed action labels emitted in client/server
log lines (e.g. `[DOWNLOAD]`, `[LOCAL CREATE]`, `[REMOTE MODIFY]`) and their
loguru colorization. Labels follow the **two-level origin rule** (ADR 0018):
`LOCAL `/`REMOTE ` prefixes mark watching events by origin (this node's watcher
vs peer-caused / inbound dispatch); the empty prefix is reserved for
reconciliation, transfers, previews and server lines.

- `ActionLabel` (`labels.py:52`) — `StrEnum` of every label: sync ops
  (`DOWNLOAD`/`UPLOAD`/`RESUME`/`MOVE`/`DELETE`/`CREATE`/`MODIFY`/
  `RENAME`/`PERMISSION`/`SYMLINK`/`IN_SYNC`/`SKIP`/`CONFLICT`/
  `GUARD`/`TOMBSTONE`), dry-run preview (`SYNCED`/`TO_*`), local-origin watcher
  (`LOCAL_*`), remote-origin / inbound (`REMOTE_*`), security/warnings
  (`SECURITY`/`NO_MASTER`/`MASTER_CONFLICT`/`MASTER_TAKEOVER`/`INSECURE_MASTER`/
  `PAIRING_NEEDED`/`FINGERPRINT_CHANGED`/`AUTH_REQUIRED`), infrastructure
  (`WS`), readiness state (`READY` — emitted by the client when watcher +
  event channel are up, category `create`).
- `LABEL_CATEGORIES` (`:127`) — semantic category → loguru color tag pair
  (transfer→cyan, upload/create→green, modify/rename→blue, delete→red,
  permission/infrastructure→magenta, in_sync→dim, warning→yellow, security→red).
  Labels are grouped by *kind* of operation, not one color per label.
- `_LABEL_CATEGORY_MAP` (`:142`) — label → category (the binding table);
  `LABEL_STYLES` (`:193`) is the derived label → color-tag view consumed by
  `colorize_labels`.
- `colorize_labels(message, use_colors)` (`labels.py:204`) — wraps every known
  label in the message with its category's color tags; a no-op when
  `use_colors=False`. Labels are processed **longest-first** so that shorter
  labels (e.g. `[DOWNLOAD]`) are never substituted inside longer prefixed
  labels (e.g. `[REMOTE DOWNLOAD]`), preventing corrupted double-wrapping.
  Wired into the loguru `message_transform` of both client
  (`hsync_client/logger.py`) and server (`hsync_server/logger.py`) formatters.
- `resolve_label(prefix, name)` (`:230`) — resolves a label stem (with optional
  `""`/`"LOCAL "`/`"REMOTE "` prefix) to its bracketed string via
  `ActionLabel`, falling back to verbatim interpolation for unregistered debug
  tags. Shared by the watchdog handlers (`BaseFileEventHandler._label`) and the
  inbound event dispatcher (`event_dispatch._tag`) so the two transports cannot
  drift apart.

> No project-local `LABEL_STYLES`/`ActionLabel` exists anymore: client
> (`hsync_client/constants.py:29`) and server (`hsync_server/constants.py:23`)
> re-export `ActionLabel` from here.

## clock.py (clock-offset SSOT, ADR-0023)

- `compute_clock_offset` (`clock.py:86`) / `measure_clock_offset` (`:123`):
  NTP-style HTTP/RTT offset against the server/master `/api/v1/time` endpoint
  (client-server mode).
  `measure_clock_offset` returns `None` on non-200 or when `timestamp` is
  missing/null/bool/non-numeric/non-finite — a malformed payload degrades the
  measurement, it never raises into the caller.
- SNTP (LAN P2P / no-server startup): `parse_ntp_hosts` (`:180`) parses the
  `HSYNC_NTP_HOSTS` CSV (defaults from `constants.NTP_DEFAULT_HOSTS`),
  `measure_clock_offset_ntp` (`:289`, median of several UDP round-trips, RFC
  4330) and `measure_clock_offset_ntp_multi` (`:318`, probes hosts in order
  until one answers). All failures ⇒ `None` ⇒ caller records offset 0 +
  degraded-temporal-mode log; sync never blocks. `_sntp_probe_once` (`:265`)
  uses a *connected* UDP socket: a dead endpoint surfaces ICMP
  port/host-unreachable as an immediate `ECONNREFUSED` (fails in ~0s instead
  of blocking for the full per-probe timeout) and datagrams from other
  sources are kernel-filtered.
- Process-local store: `ClockOffsetStore` (`:348`) + module singleton
  `offset_store` + `correct_mtime()` (`:400`) — `corrected_mtime =
  local_mtime + measured_offset` (int), consumed when a version is
  self-recorded/advertised. Never persisted, never writes the system clock.
- Anti conflict-engineering: `clamp_wire_corrected_mtime` (`:429`) clamps
  peer-supplied corrected mtimes beyond
  `constants.CORRECTED_MTIME_MAX_FUTURE_SKEW = 300 s`; the receiver-side guard
  used by every consuming hub is `clamp_incoming_corrected_mtime` (`:443`,
  reference = `now_corrected()` at `:409`, i.e. `correct_mtime(time.time())`).
  Wired in: `hsync-server` upload/delta-apply, client LAN master upload and
  remote decode; Android mirror `TimeSync.kt`.
- Android mirror: `TimeSync.kt` (same SNTP + HTTP/RTT algorithms).

> NTP defaults (`NTP_DEFAULT_HOSTS`, `NTP_PORT`, `NTP_TIMEOUT_SECONDS`,
> `NTP_PROBES_PER_HOST`, `CORRECTED_MTIME_MAX_FUTURE_SKEW`) live in
> `constants.py` Clock Synchronisation section.

## runtime.py (container / TTY / cgroup detection)

- `ContainerInfo` (`runtime.py:78`) — frozen dataclass: `is_container`,
  `runtime`, `method` (which probe produced the verdict).
- `detect_container` (`runtime.py:106`) — probes in precedence order:
  `container` env var, `/.dockerenv`, `/run/.containerenv`, runtime markers in
  `/proc/1/cgroup` (docker / podman / kubernetes / containerd). Never raises.
- `is_tty_interactive` (`runtime.py:151`) — True only when stdin **and** stdout
  are TTYs; False in containers without `-t`, systemd units, cron, pipes.
- `color_output_enabled` (`runtime.py:161`) — color gate SSOT used by the
  client/server loggers: `--no-color` flag, `NO_COLOR` env (no-color.org), TTY.
- `get_memory_limit_bytes` (`runtime.py:215`) / `get_cpu_quota_cores`
  (`runtime.py:254`) — cgroup v2 (`memory.max`, `cpu.max`) with v1 fallback;
  `None` = unlimited/unknown. Unlike `os.cpu_count()`, the CPU quota reflects
  container limits, not host hardware.
- `runtime_summary` (`runtime.py:272`) — one-line startup log line composed
  from the probes above; logged by both client (`run_sync`) and server
  (`__main__`) at startup.

## format.py / time_utils.py / text.py / env.py / exceptions.py

- `format_bytes` (`format.py:23`) renders compact binary units with **no
  separating space** (`"500B"`, `"1.5MB"`); `format_duration` (`format.py:47`)
  — `subsecond=True` renders sub-second durations as `"120ms"` / `"5.2s"` for
  transfer timing; default `False` preserves the whole-second compact style.
- `time_utils.to_epoch` (`time_utils.py`) treats **naive datetimes as UTC**
  (matching naive ISO strings): deterministic across hosts, independent of the
  caller's local timezone. `to_iso` and `conflict_timestamp` reject naive
  datetimes instead.
- `escape_loguru_markup` (`text.py:28`), `safe_json_for_log` (`text.py:38`).
- `load_env_file` (`env.py:21`).
- `HSyncError` base (`exceptions.py:30`), `format_exception` (`:63`),
  `log_exception` (`:75`).

> Human-facing summaries of compression/constants: `../docs/architecture.md`.
