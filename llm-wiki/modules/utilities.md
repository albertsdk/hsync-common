# HSYNC Common Library — Cross-cutting utilities

Leaf helpers shared by every project. Check here before writing any new
formatting/hashing/parsing helper (DRY rule in `CLAUDE.md`).

## constants.py

- `VERSION = "1.0.0"` (`constants.py:20`) — ecosystem version SSOT.
- Sentinel side-car filenames: `.hsynckeep` (`:30`), `.hsyncignore` (`:36`),
  `.hsynctombstones` (`:43`), `.hsyncstate` (`:51`).
- Adaptive chunk tiers: `CHUNK_SIZE_SMALL/MEDIUM/LARGE` (`:58`–`:60`) gated by
  `FILE_SIZE_SMALL/MEDIUM` (`:63`/`:64`).
- `PARTIAL_DOWNLOAD_SUFFIX = ".part"` (`:74`).

## hashing.py

- `is_sha256_hex` (`hashing.py:31`): wire-facing digest-shape gate — required
  before `hmac.compare_digest` (raises `TypeError` on non-ASCII input).
- `adaptive_chunk_size` (`hashing.py:46`) picks a tier from file size.
- `compute_sha256` (`hashing.py:67`) + async `compute_sha256_async`
  (`hashing.py:84`).

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
  (`.hsyncignore`/`.hsyncstate`/`.hsynctombstones`), `is_internal_name`
  (also matches `*.part`; comparison is case-insensitive so case variants
  like `.HSYNCIGNORE`/`x.PART` are rejected on case-insensitive
  filesystems), `validate_remote_relpath` (rejects `..`, absolute
  paths, drive letters, `\`, forbidden/control chars, reserved names,
  problematic trailing chars, internal artifacts), `resolve_within`
  (validation + `resolve()`/`relative_to()` confinement),
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

- `ActionLabel` (`labels.py:41`) — `StrEnum` of every label: sync ops
  (`DOWNLOAD`/`UPLOAD`/`RESUME`/`MOVE`/`DELETE`/`CREATE`/`MODIFY`/
  `RENAME`/`PERMISSION`/`SYMLINK`/`IN_SYNC`/`SKIP`/`CONFLICT`/
  `GUARD`/`TOMBSTONE`), dry-run preview (`SYNCED`/`TO_*`), local-origin watcher
  (`LOCAL_*`), remote-origin / inbound (`REMOTE_*`), security/warnings
  (`SECURITY`/`NO_MASTER`/`MASTER_CONFLICT`/`MASTER_TAKEOVER`/`INSECURE_MASTER`/
  `PAIRING_NEEDED`/`FINGERPRINT_CHANGED`/`AUTH_REQUIRED`), infrastructure
  (`WS`).
- `LABEL_CATEGORIES` (`:114`) — semantic category → loguru color tag pair
  (transfer→cyan, upload/create→green, modify/rename→blue, delete→red,
  permission/infrastructure→magenta, in_sync→dim, warning→yellow, security→red).
  Labels are grouped by *kind* of operation, not one color per label.
- `_LABEL_CATEGORY_MAP` (`:129`) — label → category (the binding table);
  `LABEL_STYLES` (`:177`) is the derived label → color-tag view consumed by
  `colorize_labels`.
- `colorize_labels(message, use_colors)` (`:183`) — wraps every known label in
  the message with its category's color tags; a no-op when `use_colors=False`.
  Wired into the loguru `message_transform` of both client
  (`hsync_client/logger.py`) and server (`hsync_server/logger.py`) formatters.
- `resolve_label(prefix, name)` (`:206`) — resolves a label stem (with optional
  `""`/`"LOCAL "`/`"REMOTE "` prefix) to its bracketed string via
  `ActionLabel`, falling back to verbatim interpolation for unregistered debug
  tags. Shared by the watchdog handlers (`BaseFileEventHandler._label`) and the
  inbound event dispatcher (`event_dispatch._tag`) so the two transports cannot
  drift apart.

> No project-local `LABEL_STYLES`/`ActionLabel` exists anymore: client
> (`hsync_client/constants.py:29`) and server (`hsync_server/constants.py:23`)
> re-export `ActionLabel` from here.

## clock.py

- `compute_clock_offset` (`clock.py:47`) / `measure_clock_offset` (`:65`);
  `CLOCK_SKEW_THRESHOLD = 5.0` (`:30`). NTP-style offset for sync timestamps.
  `measure_clock_offset` returns `None` on non-200 or when `timestamp` is
  missing/null/bool/non-numeric/non-finite — a malformed payload degrades the
  measurement, it never raises into the caller.

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

## format.py / text.py / env.py / exceptions.py

- `format_bytes` (`format.py:23`), `format_duration` (`format.py:47`) —
  `subsecond=True` renders sub-second durations as `"120ms"` / `"5.2s"` for
  transfer timing; default `False` preserves the whole-second compact style.
- `escape_loguru_markup` (`text.py:28`), `safe_json_for_log` (`text.py:38`).
- `load_env_file` (`env.py:21`).
- `HSyncError` base (`exceptions.py:30`), `format_exception` (`:63`),
  `log_exception` (`:75`).

> Human-facing summaries of compression/constants: `../docs/architecture.md`.
