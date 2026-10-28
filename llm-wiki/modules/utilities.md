# HSYNC Common Library — Cross-cutting utilities

Leaf helpers shared by every project. Check here before writing any new
formatting/hashing/parsing helper (DRY rule in `AGENTS.md`).

## constants.py

- `HSYNC_VERSION = "1.0.11"` (`constants.py::HSYNC_VERSION`) — ecosystem version SSOT.
- Wire headers `HEADER_CLIENT_NAME/CLIENT_VERSION/SERVER_VERSION/PROTOCOL_VERSION`
  plus `HEADER_CHECKSUM_SHA256` (`constants.py::HEADER_CLIENT_NAME`) — REST header names shared
  by client, server and the Android mirror; the checksum header is canonical for
  full-file server/master/seeder responses. `CLIENT_NAME_PATTERN`
  (`constants.py::CLIENT_NAME_PATTERN`) +
  `is_valid_client_name` (`constants.py::is_valid_client_name`) validate the slug shape used by server middleware.
- Wire content types `CONTENT_TYPE_OCTET_STREAM` / `CONTENT_TYPE_JSON`
  (`constants.py::CONTENT_TYPE_OCTET_STREAM`) — media types shared by the Python client/server and the
  Kotlin mirrors.
- Sentinel / engine filenames: `.hsynckeep` (`constants.py::HSYNCKEEP_FILENAME`),
  `.hsyncignore` (`constants.py::HSYNCIGNORE_FILENAME`),
  `.hsyncfolder` (`constants.py::HSYNCFOLDER_FILENAME`), plus the state-layout
  names `HSYNC_STATE_DIR_ENV` / `HSYNC_STATE_DB_ENV` and the
  `syncstate`/`server` subdir + `index.db`/`auth.db` filenames
  (`constants.py::SYNCSTATE_DIRNAME`); leftover `.hsynctombstones` / `.hsyncstate`
  (`constants.py::HSYNCTOMBSTONES_FILENAME`) stay
  rejected on the wire (ADR-0025).
- State-dir resolution: `default_state_dir` (`state_paths.py::default_state_dir`)
  owns the `HSYNC_STATE_DIR` → `$XDG_STATE_HOME/hsync` → `~/.local/state/hsync`
  order, and `state_path` (`state_paths.py::state_path`) joins a relative item
  under it while honouring a per-item env override. Every client/bootnode state
  file (device identity, server/bootnode trust stores, p2p pins, bootnode
  identity) resolves through it, so one state-dir override moves them together.
- Adaptive chunk tiers: `CHUNK_SIZE_SMALL/MEDIUM/LARGE`
  (`constants.py::CHUNK_SIZE_SMALL`) gated by
  `FILE_SIZE_SMALL/MEDIUM` (`constants.py::FILE_SIZE_SMALL`). The sub-1MB tier is 256 KiB so a
  typical burst file is read in a single iteration; measured on the HTTPS apply
  path with incompressible payloads, 8 KiB vs 256 KiB changed 5.5 → 4.3 ms
  CPU/file for a 200 KiB file, while above ~1 MiB the tier is neutral (the
  transfer itself dominates). `hsync-common/tests/test_hashing.py` guards the
  intent.
- `PARTIAL_DOWNLOAD_SUFFIX = ".part"` (`constants.py::PARTIAL_DOWNLOAD_SUFFIX`).
- `HOSTNAME_PATTERN` (`constants.py::HOSTNAME_PATTERN`) — bare hostname/IPv4 charset SSOT, consumed by
  `endpoint.py` and re-exported by `hsync_client.constants`.
- Network defaults: `BOOT_DEFAULT_PORT` (`constants.py::BOOT_DEFAULT_PORT`, boot/1 UDP)
  and `SERVER_DEFAULT_PORT` (`constants.py::SERVER_DEFAULT_PORT`, sync server TCP)
  are the single defaults for every consumer (server `Settings.port`, client
  bare-host CLI, desktop endpoint grammar/trust pre-flight).
- Far-future mtime clamp: `CORRECTED_MTIME_MAX_FUTURE_SKEW`
  (`constants.py::CORRECTED_MTIME_MAX_FUTURE_SKEW`, ADR-0023) is the only
  definition; the client and server import it (their local
  `MTIME_MAX_FUTURE_SKEW_SECONDS` names are bindings, not values).

## endpoint.py (shared `HOST[:PORT]` parser)

- `parse_host_port(raw) -> HostPort` (`endpoint.py::parse_host_port`) — the single parser for
  the combined host/port form accepted by every `hsync*` CLI. Grammar: `host`,
  `IPv4`, `host:port`, `IPv4:port`, `[IPv6]`, `[IPv6]:port`; a bare IPv6 literal
  (more than one `:`) is host-only. Port must be 1–65535; URL-like input and
  empty hosts are rejected with `ValueError`.
- `HostPort` (`endpoint.py::HostPort`) frozen dataclass: `host` (unbracketed) +
  `port: int | None`; `authority` brackets an IPv6 host for URLs/display.
- `normalize_bare_endpoint` (`endpoint.py::normalize_bare_endpoint`) — the single
  canonicalization for scheme-less `HOST[:PORT]` values (unbracketed host when no
  port, else `[IPv6]:port`; empty ⇒ `None`). Consumers: `hsync-client`
  (`HSYNC_BOOTNODE` validator) and `hsync-desktop`
  (`hsync-desktop/hsync_desktop/engine/endpoints.py::normalize_bootnode_endpoint`) so the GUI field and the
  client env var cannot normalize differently.
- `build_https_url(hp, default_port)` (`endpoint.py::build_https_url`) — canonical HTTPS URL for
  a parsed endpoint (port always explicit); used by `hsync-client` CLI and env.
- `parse_https_url(raw)` (`endpoint.py::parse_https_url`) — validates an explicit `https://` URL
  (optional port/path, IPv6-bracketed) and returns it unchanged; path is allowed
  only in this form.
- `build_url(scheme, host, port, path)` + `format_authority(host, port)`
  (`endpoint.py::build_url`) — the only host+port composites/URL builders: bracket IPv6 and
  normalize a pre-bracketed host (no double bracket). Used by `hsync-client`
  p2p, `hsync-desktop`, and the Android parity mirror.
- `parse_port_list(raw, *, strict=False) -> tuple[int, ...]`
  (`endpoint.py::parse_port_list`) — the single parser for a comma-separated UDP
  port list (order preserved, tokens `1..65535`, ASCII digits only).
  `strict=True` raises `ValueError` on the first invalid token or duplicate
  (consumed by `hsync-bootnode` `run --ports`); `strict=False` drops
  invalid/duplicate tokens (consumed by `hsync-client` `HSYNC_BOOTNODE_PORTS`).
  Empty input yields `()`; each caller enforces its own minimum.
- `is_valid_endpoint_host(host) -> bool` (`endpoint.py::is_valid_endpoint_host`) —
  the dialable-host grammar of the wire: IPv4/IPv6 literal (bracketed or bare) or
  LDH hostname, rejecting control characters, path/authority separators, empty
  labels, labels > 63 chars and IPv4-shaped non-addresses. Consumed by the
  bootnode `protocol.Endpoint` model and by this mirror's `_validate_endpoint`,
  so an advertised `endpoints[].host` is the same grammar on both ends.
- Consumers: `hsync-client` `cli.py` (bootnode/server/trust host args),
  `hsync-bootnode` `cli.py` (`run --host HOST[:PORT]`), `hsync-server`
  `__main__.py` (`--host HOST[:PORT]`). The same grammar applies to the
  environment: `HSYNC_SERVER` (`host`, `host:port`, `[IPv6]`, `[IPv6]:port`,
  or a full `https://…[/path]`) and `HSYNC_BOOTNODE` (same, no scheme/path).

## hashing.py

- `is_sha256_hex` (`hashing.py::is_sha256_hex`): wire-facing digest-shape gate — required
  before `hmac.compare_digest` (raises `TypeError` on non-ASCII input).
- `is_lower_sha256_hex` (`hashing.py::is_lower_sha256_hex`): lowercase-only variant, single
  definition for the tombstone keys and the peer-download keys
  (`tombstone._is_valid_key`, `peer_download._is_lower_sha256`).
- `adaptive_chunk_size` (`hashing.py::adaptive_chunk_size`) picks a tier from file size.
- `compute_sha256` (`hashing.py::compute_sha256`) + async `compute_sha256_async`
  (`hashing.py::compute_sha256_async`) — the async variant imports `asyncio` **inside** the
  coroutine, so importing this module (e.g. through
  `protocol.pairing` on the client CLI fast path) never pays the `asyncio`
  startup cost; keep it that way when refactoring.

## delta/rolling_checksum.py

- `compute_signatures(filepath, block_size)` (streamed, bounded memory) and
  `signatures_for_data(data, block_size)` (in-memory twin for fixture/test
  builders) share the same per-chunk weak+strong helper, so the two paths
  cannot drift.
- `reconstruct_and_verify` (`delta/reconstruct.py::reconstruct_and_verify`) — the
  receiver-side invariant: apply the ops into the caller's `*.delta.part`, then
  prove the rebuild with `expected_sha256` + `expected_size`, raising
  `ReconstructionMismatch` (`delta/reconstruct.py::ReconstructionMismatch`, a
  `DeltaError` whose `details["reason"]` is `MISMATCH_HASH`/`MISMATCH_SIZE`).
  Consumers: server `api/files/delta/apply.py`, client
  `p2p_delta.handle_delta_apply` and `delta_transfer.download_file_delta`, each
  mapping the reason to its own error surface.

## compression.py (Zstandard, level 3)

- `should_compress` (`compression.py::should_compress`) — size/extension gate.
- `compress_data`/`decompress_data` (`compression.py::compress_data`), `compress_file` (`compression.py::compress_file`),
  `compress_file_to_file` (`compression.py::compress_file_to_file`) — streaming src→dst compression with
  memory bounded by the read chunk (production upload paths; `compress_file`
  itself is memory-capped test-only).
- `decompress_data(data, max_output_size=...)` enforces a hard cap on the
  decompressed size via a capped streaming read — mandatory for wire-supplied
  payloads (anti decompression-bomb). `decompress_stream`
  (`compression.py::decompress_stream`) is the
  streaming variant for HTTP response bodies (yields capped chunks).
- Thresholds: `MIN_SIZE_FOR_COMPRESSION` 10 KB (`compression.py::MIN_SIZE_FOR_COMPRESSION`),
  upload `MIN_SIZE_FOR_UPLOAD` 32 KB (`compression.py::MIN_SIZE_FOR_UPLOAD`),
  p2p `MIN_SIZE_FOR_P2P` 100 KB (`compression.py::MIN_SIZE_FOR_P2P`) — the
  download direction reuses the `MIN_SIZE_FOR_COMPRESSION` floor;
  `PRECOMPRESSED_EXTENSIONS` frozenset (`compression.py::PRECOMPRESSED_EXTENSIONS`);
  encoding token `CONTENT_ENCODING_ZSTD` (`compression.py::CONTENT_ENCODING_ZSTD`).
  Direction-aware level SSOT: `compression_level` (`compression.py::compression_level`)
  returns `COMPRESSION_LEVEL_FAST` for upload/p2p and `COMPRESSION_LEVEL` for
  download.
- **Thread safety**: zstd instances are **per-thread** via
  `_ThreadLocalZstd` (`compression.py::_ThreadLocalZstd`, a `threading.local()`
  subclass) held in `_zstd_tls` (`compression.py::_zstd_tls`). A decompressor is
  NOT safe for concurrent `decompressobj()` calls — a single module-level
  shared instance corrupted streams (and, with zstandard ≥ 0.25, crashed the
  interpreter) when parallel transfers decompressed simultaneously
  (`hsync-client` parallel downloads/`decompress_stream`). Compression uses the
  per-thread compressor cache (`_compressor_for`, `compression.py::_compressor_for`),
  so no shared mutable decompressor state is ever exposed. Consumers: `hsync-client`
  (parallel transfer threads), `hsync-server` (upload/delta ingestion),
  mirrored fixtures/tests.

## permissions.py (octal SSOT)

- `mode_to_octal` (`permissions.py::mode_to_octal`), `octal_to_mode` (`permissions.py::octal_to_mode`),
  `is_valid_octal_permissions` (`permissions.py::is_valid_octal_permissions`),
  `get_permissions` (`permissions.py::get_permissions`);
  `PERMISSION_MASK = 0o7777` (`permissions.py::PERMISSION_MASK`). Used by `File`/`Dir` and the server upload
  form.
- **Asymmetric special-bits policy** (ADR-0026, `../docs/internal/adr/0026-permission-special-bits-policy.md`):
  - *Read/serialize* keeps the full 12 bits — `mode_to_octal` masks to
    `PERMISSION_MASK = 0o7777`, so a local `setuid` file is transmitted as
    `"4755"` and a special-bit chmod is detected as a permission change (client
    snapshot key uses `st_mode & 0o7777`).
  - *Apply* strips them: `REMOTE_PERMISSION_MASK = 0o777` (`permissions.py::REMOTE_PERMISSION_MASK`) and
    `sanitize_remote_permissions` (`permissions.py::sanitize_remote_permissions`) drop setuid/setgid/sticky from
    peer-supplied strings, so `"4755"` is applied as `"755"`. A remote peer can
    never create a setuid/setgid/sticky object on this host.
  - *Directory floor*: `OWNER_DIRECTORY_ACCESS = 0o700` (`permissions.py::OWNER_DIRECTORY_ACCESS`) is OR-ed onto
    peer-supplied directory modes by the apply helper so a peer `000` can never
    lock the storage owner out of its own tree.
- Apply: `apply_remote_permissions` (`permissions.py::apply_remote_permissions`)
  is the single receiver-side applier (sanitize → mode → OR-floor for
  directories → `chmod`; `skip_if_equal` avoids a redundant syscall and returns
  `None`). Consumers wrap it only for their own concern: client
  `hsync-client/hsync_client/utils/permissions.py::set_permissions`/`set_permissions_on_dir` (sync,
  `skip_if_equal=True`, debug log) and server
  `hsync-server/hsync_server/api/utils.py::set_permissions`/`set_directory_permissions`
  (`await to_thread(...)`). Metadata-only `PATCH …/files/permissions` (client
  `patch_permissions_remote`, server `api/files/permissions.py`) routes through
  the same wrappers. Tests: `hsync-common/tests/test_permissions.py`,
  `hsync-client/tests/test_security_inbound.py`.

## path_validation.py

- `basename` (`path_validation.py::basename`): last path component without a
  `Path` allocation (hot scan path; used by `File`, `is_partial_file`,
  `IgnoreMatcher.matches`).
- Char/name guards: `has_forbidden_chars`, `has_control_chars`,
  `is_reserved_name`, `has_problematic_trailing`.
- `is_valid_filename` (`path_validation.py::is_valid_filename`), traversal guards
  `has_dotdot_component` (`path_validation.py::has_dotdot_component`),
  `is_safe_path_component` (`path_validation.py::is_safe_path_component`),
  `safe_resolve_path` (`path_validation.py::safe_resolve_path`).
- Bucket names: `BUCKET_NAME_PATTERN` (`path_validation.py::BUCKET_NAME_PATTERN`),
  `is_valid_bucket_name` (`path_validation.py::is_valid_bucket_name`).
- `sanitize_filename` (`path_validation.py::sanitize_filename`).
- Wire-facing remote-path validation (`path_validation.py::validate_remote_relpath`):
  `INTERNAL_FILENAMES`
  (`.hsyncignore`/`.hsyncfolder`/`.hsyncstate`/`.hsynctombstones`), `is_internal_name`
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
  client upload `transfer.upload_file`, p2p master listing/download
  `p2p_server`, server listing/download `api/files/*`, WS event handlers)
  uses it to refuse symlinks whose target escapes the bucket.
- Event-payload path keys: `WIRE_PATH_KEYS` + `wire_relpaths`
  (`path_validation.py::wire_relpaths`) —
  SSOT for the set of path-carrying keys (`filepath`, `path`) used by both
  the server relay gate and the client dispatcher.

## ignore.py (.hsyncignore matcher)

- `IgnoreMatcher` (`ignore.py::IgnoreMatcher`, pathspec-backed). Process-global active
  matcher: `set_active_matcher` (`ignore.py::set_active_matcher`), `get_active_matcher` (`ignore.py::get_active_matcher`),
  `should_skip` (`ignore.py::should_skip`). `.part` files and `INTERNAL_FILENAMES` are always
  excluded. `_to_relative` strips only a
  leading `./`, so user patterns can match dotfiles.

## ssl_utils.py (TLS identity)

- `SERVICE_CERT_VALIDITY_DAYS` (7305) — the shared 20-year validity for
  self-signed service identities (ADR-0037); `build_self_signed_certificate`
  (`ssl_utils.py::build_self_signed_certificate`) backdates `NotBefore` by one day for clock skew.
- `generate_ecdsa_private_key` (`ssl_utils.py::generate_ecdsa_private_key`, P-256) — the key type of every HSYNC
  service identity (ADR-0037); `generate_rsa_private_key` (`ssl_utils.py::generate_rsa_private_key`,
  `DEFAULT_KEY_SIZE = 2048`) and `generate_ed25519_private_key` (`ssl_utils.py::generate_ed25519_private_key`) are
  alternate generators that `build_self_signed_certificate` also accepts
  (RSA/ECDSA/Ed25519, `PrivateKey` type alias; Ed25519 signs with no hash
  parameter), used by tests.
- Serialization: PEM cert/key, unencrypted PKCS#8
  `serialize_private_key_unencrypted` (`ssl_utils.py::serialize_private_key_unencrypted`; RSA, ECDSA or Ed25519).
- Fingerprints: `compute_cert_fingerprint`, `verify_cert_fingerprint` — the DER
  SHA-256 domain shared with the service trust contract (ADR-0034/ADR-0037).
- Persistence: `write_pem_keypair` (`ssl_utils.py::write_pem_keypair`) /
  `load_pem_keypair` (`ssl_utils.py::load_pem_keypair`) — the single implementation
  of "write an identity pair with permission-enforced files" (key `0o600`,
  directory `0o700`, modes in `KEY_FILE_MODE`/`PUBLIC_CERT_FILE_MODE`/
  `IDENTITY_DIR_MODE`) and of loading one back (ECDSA-only validation, stable
  fingerprint). Consumers: `hsync-server` (server TLS certificate, public
  `0o644` cert) and `hsync-client` (P2P master identity, owner-only pair).
- Identity operations: `create_service_identity` (`ssl_utils.py::create_service_identity`,
  always regenerates — rotation) and `load_or_create_service_identity`
  (`ssl_utils.py::load_or_create_service_identity`, loads when both files exist,
  else generates) returning `ServiceIdentity`
  (`ssl_utils.py::ServiceIdentity`: cert/key PEM, fingerprint, paths, `created`,
  `not_valid_after`). Consumers supply only subject/SAN/file modes:
  `hsync-server` `ssl_utils.generate_self_signed_cert` (rotation) and
  `ensure_certificates` (an operator-provided pair is used as-is, any key type),
  `hsync-client` `ssl_utils.load_or_create_master_cert`. The bootnode keeps its
  own combined-PEM load/rotate (single-file identity + key/cert match check).

## logger.py

- `BaseInterceptHandler` (`logger.py::BaseInterceptHandler`) routes stdlib logging into loguru with
  markup escaping. `LEVEL_STYLES` (`logger.py::LEVEL_STYLES`); rotation defaults and
  `get_rotation_config` (`logger.py::get_rotation_config`); `build_record_formatter`
  (`logger.py::build_record_formatter`); `configure_handlers` (`logger.py::configure_handlers`).

## labels.py (action-label & colorization SSOT)

Single source of truth for the bracketed action labels emitted in client/server
log lines (e.g. `[DOWNLOAD]`, `[LOCAL CREATE]`, `[REMOTE MODIFY]`) and their
loguru colorization. Labels follow the **two-level origin rule** (ADR 0018):
`LOCAL `/`REMOTE ` prefixes mark watching events by origin (this node's watcher
vs peer-caused / inbound dispatch); the empty prefix is reserved for
reconciliation, transfers, previews and server lines.

- `ActionLabel` (`labels.py::ActionLabel`) — `StrEnum` of every label: sync ops
  (`DOWNLOAD`/`UPLOAD`/`RESUME`/`MOVE`/`DELETE`/`CREATE`/`MODIFY`/
  `RENAME`/`PERMISSION`/`SYMLINK`/`IN_SYNC`/`SKIP`/`CONFLICT`/
  `GUARD`/`TOMBSTONE`), dry-run preview (`SYNCED`/`TO_*`), local-origin watcher
  (`LOCAL_*`), remote-origin / inbound (`REMOTE_*`), security/warnings
  (`SECURITY`/`NO_MASTER`/`MASTER_CONFLICT`/`MASTER_TAKEOVER`/`MASTER_YIELD`/
  `INSECURE_MASTER`/`PAIRING_NEEDED`/`FINGERPRINT_CHANGED`/`AUTH_REQUIRED`/`WATCHER_ERROR` — the
  client emits the latter when its local file watcher cannot start because the
  kernel inotify limits are exhausted, category `warning`), infrastructure
  (`WS`), lifecycle phase (`INITIAL_SYNC` — emitted by the client at the start
  of a run's first full reconcile, category `phase`), readiness state (`READY`
  — emitted by the client when watcher + event channel are up, category `create`).
- `LABEL_CATEGORIES` (`labels.py::LABEL_CATEGORIES`) — semantic category → loguru color tag pair
  (transfer→cyan, upload/create→green, modify/rename→blue, delete→red,
  permission/infrastructure→magenta, in_sync→dim, warning→yellow, security→red,
  phase→bold white). Labels are grouped by *kind* of operation, not one color
  per label.
- `_LABEL_CATEGORY_MAP` (`labels.py::_LABEL_CATEGORY_MAP`) — label → category (the binding table);
  `LABEL_STYLES` (`labels.py::LABEL_STYLES`) is the derived label → color-tag view consumed by
  `colorize_labels`.
- `colorize_labels(message, use_colors)` (`labels.py::colorize_labels`) — wraps every known
  label in the message with its category's color tags; a no-op when
  `use_colors=False`. Labels are processed **longest-first** so that shorter
  labels (e.g. `[DOWNLOAD]`) are never substituted inside longer prefixed
  labels (e.g. `[REMOTE DOWNLOAD]`), preventing corrupted double-wrapping.
  Wired into the loguru `message_transform` of both client
  (`hsync_client/logger.py`) and server (`hsync_server/logger.py`) formatters.
- `resolve_label(prefix, name)` (`labels.py::resolve_label`) — resolves a label stem (with optional
  `""`/`"LOCAL "`/`"REMOTE "` prefix) to its bracketed string via
  `ActionLabel`, falling back to verbatim interpolation for unregistered debug
  tags. Shared by the watchdog handlers (`BaseFileEventHandler._label`) and the
  inbound event dispatcher (`event_dispatch._tag`) so the two transports cannot
  drift apart.

> `LABEL_STYLES`/`ActionLabel` live only here: client
> (`hsync_client/constants.py::ActionLabel`) and server (`hsync_server/constants.py::ActionLabel`)
> re-export `ActionLabel` from here.

## clock.py (clock-offset SSOT, ADR-0023)

- `compute_clock_offset` (`clock.py::compute_clock_offset`) / `measure_clock_offset` (`clock.py::measure_clock_offset`):
  NTP-style HTTP/RTT offset against the server/master `/api/v1/time` endpoint
  (client-server mode).
  `measure_clock_offset` returns `None` on non-200 or when `timestamp` is
  missing/null/bool/non-numeric/non-finite — a malformed payload degrades the
  measurement, it never raises into the caller.
- SNTP (p2p / no-server startup): `parse_ntp_hosts` (`clock.py::parse_ntp_hosts`) parses the
  `HSYNC_NTP_HOSTS` CSV (defaults from `constants.NTP_DEFAULT_HOSTS`),
  `measure_clock_offset_ntp` (`clock.py::measure_clock_offset_ntp`, median of several UDP round-trips, RFC
  4330) and `measure_clock_offset_ntp_multi` (`clock.py::measure_clock_offset_ntp_multi`, probes hosts in order
  until one answers). All failures ⇒ `None` ⇒ caller records offset 0 +
  degraded-temporal-mode log; sync never blocks. `_sntp_probe_once` (`clock.py::_sntp_probe_once`)
  uses a *connected* UDP socket: a dead endpoint surfaces ICMP
  port/host-unreachable as an immediate `ECONNREFUSED` (fails in ~0s instead
  of blocking for the full per-probe timeout) and datagrams from other
  sources are kernel-filtered.
- Process-local store: `ClockOffsetStore` (`clock.py::ClockOffsetStore`) + module singleton
  `offset_store` + `correct_mtime()` (`clock.py::correct_mtime`) — `corrected_mtime =
  local_mtime + measured_offset` (int), consumed when a version is
  self-recorded/advertised. `begin_epoch` / `end_epoch` freeze that basis for
  one sync cycle so a late NTP `record()` cannot mix clocks mid-cycle
  (consumer: `hsync-client` `sync()`). Never persisted, never writes the
  system clock.
- Anti conflict-engineering: `clamp_wire_corrected_mtime` (`clock.py::clamp_wire_corrected_mtime`) clamps
  peer-supplied corrected mtimes beyond
  `constants.CORRECTED_MTIME_MAX_FUTURE_SKEW = 300 s`; the receiver-side guard
  used by every consuming hub is `clamp_incoming_corrected_mtime` (`clock.py::clamp_incoming_corrected_mtime`,
  reference = `now_corrected()` at `clock.py::now_corrected`, i.e. `correct_mtime(time.time())`).
  Wired in: `hsync-server` upload/delta-apply, client p2p master upload and
  remote decode; Android mirror `TimeSync.kt`.
- Metadata convergence: `constants.MTIME_PROPAGATION_TOLERANCE_SECONDS = 1 s`
  is the divergence threshold above which a content-identical `touch` is
  propagated. Consumers: `hsync-client` `sync.get_sync_actions` /
  `sync_state.mtime_diverges`, `hsync-server`
  `apply_metadata_to_existing_file`, client LAN PATCH handler.
- `uncorrect_mtime` (`clock.py::uncorrect_mtime`, inverse of `correct_mtime`) converts a
  wire-supplied corrected time back to the local raw clock before writing it to
  the filesystem. Consumers: `hsync-client` (`sync._apply_local_mtime`, LAN
  master PATCH handler), `hsync-android` mirror.
- Android mirror: `TimeSync.kt` (same SNTP + HTTP/RTT algorithms).

> NTP defaults (`NTP_DEFAULT_HOSTS`, `NTP_PORT`, `NTP_TIMEOUT_SECONDS`,
> `NTP_PROBES_PER_HOST`, `CORRECTED_MTIME_MAX_FUTURE_SKEW`) live in
> `constants.py` Clock Synchronisation section.

## models/arbitration.py (causal upload gate, ADR-0022)

- `decide_arbitration` (`arbitration.py::decide_arbitration`) — pure decision
  for an incoming version against the stored one: tolerant wire-vclock parse,
  `resolve_three_way`, then the outcome mapping
  (`accepted` / `accepted_conflict_won` / `superseded` / `conflict_lost`) plus
  the clock and corrected mtime the receiver must record. Persistence-free: the
  caller reads/applies its own store.
- `plan_self_record` (`arbitration.py::plan_self_record`) — the out-of-band
  anti-aliasing advance (disk content ≠ stored base) as a `SelfRecord`
  (`arbitration.py::SelfRecord`), applied by the caller under its own CID.
- `conflicted_copy_name` (`arbitration.py::conflicted_copy_name`) — canonical
  `<stem>_conflicted_copy_<ts>_<cid>.<ext>` loser path (ADR-0021).
- Consumers: `hsync-server/arbitration.py` and `hsync-client/arbitration.py`
  (thin store/CID bindings), shared tests.

## models/sentinel.py (`.hsynckeep` lifecycle)

- `ensure_sentinel` (`sentinel.py::ensure_sentinel`) — create the marker only
  when the directory has no syncable entry; `is_sentinel_file`
  (`sentinel.py::is_sentinel_file`) and `remove_empty_dir`
  (`sentinel.py::remove_empty_dir`, `keep_root` guard) own the reverse rule.
- Consumers: server delete path (`api/file_utils.py`) and client
  (`sync.ensure_sentinel`, `utils.paths.safe_rmdir_if_empty`), so both leave the
  same tree.

## delta/token_store.py (single-use download tokens)

- `DeltaTokenStore` (`token_store.py::DeltaTokenStore`) — TTL + count/storage
  caps, lazy expiry, cached storage accounting, atomic payload adoption
  (`issue` / `issue_from_file` / `lookup` / `is_expired` / `consume` /
  `discard` / `reset`). `DeltaTokenEntry` (`token_store.py::DeltaTokenEntry`)
  carries `bucket`/`compressed`/`meta`; `TokenStoreFull` /
  `TokenStoreStorageFull` are the two capacity refusals.
- Consumers: `hsync-server/api/files/delta/tokens.py` (metrics + bucket dir) and
  `hsync-client/p2p_delta.py` (process temp dir), tests.

## defaults.py (CLI/GUI shared defaults)

- User-facing defaults that must agree between the `hsync` CLI and the desktop
  GUI, which cannot import the client package: `HTTP_TIMEOUT_DEFAULT`,
  `STABILITY_DELAY_DEFAULT`, `RECONNECT_DELAY_DEFAULT`,
  `SYNC_DIRECTION_DEFAULT`, `MAX_CONCURRENT_TRANSFERS_DEFAULT`,
  `MASS_DELETE_GUARD_DEFAULT`, `MASS_DELETE_THRESHOLD_DEFAULT`,
  `MASS_DELETE_PERCENT_DEFAULT`, `MIN_FREE_DISK_SPACE_DEFAULT`,
  `MAX_INBOUND_SIZE_MB_DEFAULT`, `BANDWIDTH_MIN_BPS`, `BANDWIDTH_MAX_BPS`,
  `MAX_WAIT_TIMEOUT_DEFAULT`, `P2P_PEER_DOWNLOAD_DEFAULT`,
  `P2P_PEER_READ_CAP_DEFAULT`, `P2P_PEER_SOURCES_MAX_DEFAULT`,
  `DELETION_POLICIES` and `DELETION_POLICY_DEFAULT`.
- `DELETION_POLICIES` (`propagate`/`keep`) is the deletion-policy vocabulary
  shared by `hsync-client` (`--deletion-policy` / `HSYNC_DELETION_POLICY`, read
  once through
  `hsync-client/hsync_client/config.py::deletions_are_kept`), `hsync-desktop`
  (aliased as `hsync-desktop/hsync_desktop/config.py::DELETION_POLICIES`, used by
  the Sync-tab combo and the backup badge) and the Kotlin mirror
  `hsync-android/app/src/main/java/com/hsync/android/domain/model/DeletionPolicy.kt::DeletionPolicy`.
- `MIN_FREE_DISK_SPACE_DEFAULT`/`_MIN`/`_MAX` are **bytes** (500 MiB / 0 /
  100 GiB): the unit `shutil.disk_usage` reports. The operator-facing form is a
  size string parsed by `format.py::parse_size` (see `disk.py` below); the
  desktop derives its MB spin-box bounds with `disk.py::BYTES_PER_MB`.
- The accepted range of every bounded knob lives here too: the `*_MIN`/`*_MAX`
  pairs for HTTP timeout, stability delay, max-wait timeout, reconnect delay,
  resync interval, concurrent transfers, free-space/inbound caps and the p2p
  caps (`defaults.py::MAX_WAIT_TIMEOUT_MIN`). The CLI validates against them and
  the GUI clamps to them, so a value the GUI emits is always accepted by the CLI.
- `MAX_WAIT_TIMEOUT_DEFAULT` (`defaults.py::MAX_WAIT_TIMEOUT_DEFAULT`) is the
  upper bound on one upload slot's stability wait. The wait ends as soon as
  size+mtime settle, so it does not penalise large files; keeping it short bounds
  how long a pooled slot can be parked by a file that never settles.
- `hsync_client.constants` and `hsync_desktop.config` re-export the values and
  bounds under their own names; GUI-only guardrails (a taller minimum than the
  CLI allows) and GUI-exclusive defaults stay in `hsync_desktop/config.py`.
  Consumers: `hsync-client`, `hsync-desktop`, tests
  (`hsync-common/tests/test_defaults_bounds.py`,
  `hsync-desktop/tests/test_defaults_parity.py`,
  `hsync-client/tests/test_cli_option_parity.py`).

## runtime.py (container / TTY / cgroup detection)

- `ContainerInfo` (`runtime.py::ContainerInfo`) — frozen dataclass: `is_container`,
  `runtime`, `method` (which probe produced the verdict).
- `detect_container` (`runtime.py::detect_container`) — probes in precedence order:
  `container` env var, `/.dockerenv`, `/run/.containerenv`, runtime markers in
  `/proc/1/cgroup` (docker / podman / kubernetes / containerd). Never raises.
- `is_tty_interactive` (`runtime.py::is_tty_interactive`) — True only when stdin **and** stdout
  are TTYs; False in containers without `-t`, systemd units, cron, pipes.
- `color_output_enabled` (`runtime.py::color_output_enabled`, `runtime.py::ColorMode`) — color
  gate SSOT used by the client/server loggers and forced by the Desktop (which
  captures the client's pipe): `auto` = TTY + `NO_COLOR` env (no-color.org),
  `always` = forced (wins over `NO_COLOR`), `never` = off. An unknown mode raises.
- `get_memory_limit_bytes` (`runtime.py::get_memory_limit_bytes`) / `get_cpu_quota_cores`
  (`runtime.py::get_cpu_quota_cores`) — cgroup v2 (`memory.max`, `cpu.max`) with v1 fallback;
  the memory limit resolves the process's **own** (possibly nested) cgroup from
  `/proc/self/cgroup` first (`_process_cgroup_memory_limit`), so a systemd
  `MemoryMax=` or a service slice is honoured, then falls back to the mount root.
  `None` = unlimited/unknown. Unlike `os.cpu_count()`, the CPU quota reflects
  container limits, not host hardware. Consumers: `hsync-client`
  (`_get_optimal_workers`: the CPU quota sizes the parallel scan/hash pool and
  the memory limit additionally caps it inside containers, 8 MiB/worker budget;
  on bare metal the memory probe is `None` and only the CPU quota applies),
  `hsync-bootnode` (`resources.py`), `runtime_summary`.
- `total_memory_bytes` (`runtime.py::total_memory_bytes`) / `available_memory_bytes`
  (`runtime.py::available_memory_bytes`) — `sysconf` physical RAM and
  `/proc/meminfo` `MemAvailable` capped by the cgroup limit; `None` when the
  source is unreadable (the bootnode then applies its conservative fallback).
- `runtime_summary` (`runtime.py::runtime_summary`) — one-line startup log line composed
  from the probes above; logged by both client (`run_sync`) and server
  (`__main__`) at startup.

## format.py / time_utils.py / text.py / env.py / exceptions.py

- `format_bytes` (`format.py::format_bytes`) renders compact binary units with **no
  separating space** (`"500B"`, `"1.5MB"`); `parse_size` (`format.py::parse_size`) is
  its inverse: it parses `"500MB"`/`"2GB"`/`"0"` (binary multiples, `K`/`KiB`
  spellings accepted, `require_unit=True` rejects a bare non-zero number) into
  bytes, and is the single parser behind `--min-free-disk-space`,
  `HSYNC_MIN_FREE_DISK_SPACE`, the WD OS5 field and `hsync-client/hsync_client/utils/throttle.py::parse_bandwidth`;
  `format_duration` (`format.py::format_duration`)
  — `subsecond=True` renders sub-second durations as `"120ms"` / `"5.2s"` for
  transfer timing; default `False` preserves the whole-second compact style.
- `time_utils.to_epoch` (`time_utils.py::to_epoch`) treats **naive datetimes as UTC**
  (matching naive ISO strings): deterministic across hosts, independent of the
  caller's local timezone. `to_iso` and `conflict_timestamp` reject naive
  datetimes instead.
- `escape_loguru_markup` (`text.py::escape_loguru_markup`), `safe_json_for_log` (`text.py::safe_json_for_log`),
  `compact_json_str` / `compact_json_bytes` (`text.py::compact_json_str`): the single canonical compact
  wire-JSON encoder (`ensure_ascii=False`, `allow_nan=False`, `separators=(",", ":")`), shared by
  the hsync-client LAN payloads (byte responses and `aiohttp`/`websockets` text frames),
  the hsync-server streamed listing body and `protocol.peer_download` limits.
- `load_env_file` (`env.py::load_env_file`).
- `HSyncError` base (`exceptions.py::HSyncError`) with `to_dict()` JSON
  serialization; each project subclasses it with its own `error_code` /
  `default_message`.

> Human-facing summaries of compression/constants: `../docs/architecture.md`.

## upnp.py (SSDP/SOAP IGD client, SSRF-hardened)

- `discover_igd(timeout=2.0, local_ip=None)` (`upnp.py::discover_igd`) — M-SEARCH over SSDP,
  then a reply gate that refuses an off-LAN source, a non-http(s)/non-private-IP
  `LOCATION`, and a `LOCATION` host different from the reply source
  (`_location_host_matches_source`). `_first_igd_location` takes an optional
  `fetch` seam (tests/fuzz).
- Validators: `is_lan_unicast_address` (RFC1918 + ULA `fc00::/7`; no link-local,
  loopback or public), `is_private_http_location` (http(s) IP-literal only; no
  hostname/userinfo), `_control_url_on_base` (relative only; no host escape),
  `no_redirect_urlopen` / `_NoRedirect` (a 3xx is never followed).
- SOAP: `build_add_mapping_soap` / `build_delete_mapping_soap`,
  `add_port_mapping` / `delete_port_mapping`, `parse_soap_error`; `_soap_post`
  accepts an `http_post` transport seam. Every XML body (description and SOAP
  fault) goes through `_parse_bounded_xml`: read capped at `_MAX_XML_BODY_BYTES`
  and refused when it carries `<!DOCTYPE`/`<!ENTITY`, so a device cannot expand
  entities beyond the bytes it sent.
- Consumers: `hsync-client` `upnp.py` (`UpnpMapper`, TCP), `hsync-bootnode/python`
  `upnp.py` (`UpnpManager`, UDP; re-exports the core for its tests/fuzz).

## listing.py (bucket listing SSOT)

The bucket listing published to peers is the same on every surface — hidden /
ignored entries filtered, symlinks emitted structurally and never dereferenced,
bucket-relative paths, deterministic order, streamed JSON array body:

- `iter_json_array` (`listing.py::iter_json_array`) — `[` / item / `,` / `]`
  generator using `compact_json_bytes`; consumed by the server's
  `StreamingResponse` (`get_files`, `get_dirs`).
- `iter_dir_entries` (`listing.py::iter_dir_entries`) — `{path, permissions}` per
  directory (dir-symlinks skipped); server `GET …/dirs` and client
  `p2p_server._handle_list_dirs`.
- `iter_bucket_entries` (`listing.py::iter_bucket_entries`) — `(abs_path,
  Symlink | None)` walk with the hidden filters and the
  `is_safe_symlink_target` confinement check; `start_dir` (server subdirectory
  listing), `skip_suffixes` (server `BACKUP_SUFFIX`) and
  `include_dir_symlinks` (server lists dir-symlinks, the client's sync scan does
  not). Consumers: `hsync-client` `sync.iter_bucket_entries` (wrapper) and
  `p2p_server._handle_list_files`, `hsync-server`
  `api/files/list.py._iter_file_entries`.
- `file_entry` (`listing.py::file_entry`) / `symlink_entry`
  (`listing.py::symlink_entry`) — the wire dict with a bucket-relative
  `filepath` (a path outside the bucket is kept verbatim); `symlink_entry`
  returns `None` for an escaping target.

## disk.py (free-space guards)

- `check_free_space` (`disk.py::check_free_space`) — the single "can this
  filesystem hold the write" rule: `free >= reserve_bytes + incoming_bytes`,
  returning `FreeSpaceCheck` (`disk.py::FreeSpaceCheck`: `ok`, `free_bytes`,
  `required_bytes`, `error`, plus `free_mb`/`required_mb` for messages). A probe
  failure (`OSError`) yields `ok=True` + `error`, never a rejection; a
  non-positive reserve disables the check. The reserve is always **bytes**: the
  unit `shutil.disk_usage` reports and the one every consumer stores.
- One operator surface exists for that reserve: a size string (`"500MB"`,
  `"2GB"`, `"0"` = disabled) parsed by `format.py::parse_size` into bytes —
  `--min-free-disk-space` (client), `HSYNC_MIN_FREE_DISK_SPACE` (server,
  `hsync-server/hsync_server/config.py::Settings.validate_min_free_disk_space`), the desktop spin box
  (whole MB, emitted as `"<n>MB"`) and the WD OS5 form.
- Consumers: `hsync-server` `hsync-server/hsync_server/api/utils.py::ensure_disk_space`,
  `hsync-client` `transfer.py` (per-download guard), `p2p_server.py`
  (LAN-master upload guard) and `hsync-client/hsync_client/main_logic.py::_check_disk_space` (startup
  check) — all in bytes.

## ratelimit.py (shared token bucket)

- `TokenBucketLimiter(capacity, refill, window, max_keys=...)` (`ratelimit.py::TokenBucketLimiter`) —
  RAM-only, monotonic, lazy refill; `allow`/`has_tokens`/`retry_after`/
  `evict_stale`; `max_keys` evicts the LRU key so IP/bucket churn cannot grow the
  map unbounded (peeks never refresh recency, only a real `allow` does).
- Consumers: `hsync-client` `p2p_server` (per-IP new-request admission;
  `P2P_REQ_RATE_*`), `hsync-bootnode/python` `ratelimit.py` (facade over the
  shared class for its admission/query/register limits).
