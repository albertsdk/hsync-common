# hsync-common — Cross-cutting utilities

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

- `adaptive_chunk_size` (`hashing.py:31`) picks a tier from file size.
- `compute_sha256` (`hashing.py:52`) + async `compute_sha256_async`
  (`hashing.py:69`).

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
  (also matches `*.part`), `validate_remote_relpath` (rejects `..`, absolute
  paths, drive letters, `\`, forbidden/control chars, reserved names,
  problematic trailing chars, internal artifacts), `resolve_within`
  (validation + `resolve()`/`relative_to()` confinement),
  `is_safe_symlink_target` (SSOT, shared with the server).

## ignore.py (.hsyncignore matcher)

- `IgnoreMatcher` (`ignore.py:41`, pathspec-backed). Process-global active
  matcher: `set_active_matcher` (`:163`), `get_active_matcher` (`:176`),
  `should_skip` (`:182`). `.part` files and `INTERNAL_FILENAMES` are always
  excluded, even with `include_hidden=True`. `_to_relative` strips only a
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

## clock.py

- `compute_clock_offset` (`clock.py:46`) / `measure_clock_offset` (`:64`);
  `CLOCK_SKEW_THRESHOLD = 5.0` (`:29`). NTP-style offset for sync timestamps.

## format.py / text.py / env.py / exceptions.py

- `format_bytes` (`format.py:23`), `format_duration` (`format.py:47`).
- `escape_loguru_markup` (`text.py:28`), `safe_json_for_log` (`text.py:38`).
- `load_env_file` (`env.py:21`).
- `HSyncError` base (`exceptions.py:30`), `format_exception` (`:63`),
  `log_exception` (`:75`).

> Human-facing summaries of compression/constants: `../docs/architecture.md`.
