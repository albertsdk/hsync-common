# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Log label format normalized to spaces**: multi-word `ActionLabel` *values*
  (the strings emitted in logs) now use spaces instead of underscores — e.g.
  `[NO MASTER]`, `[TO DOWNLOAD]`, `[FINGERPRINT CHANGED]` instead of
  `[NO_MASTER]`/`[TO_DOWNLOAD]`/`[FINGERPRINT_CHANGED]`. The enum *member* names
  stay snake_case (`NO_MASTER`, `TO_DOWNLOAD`, …) and `resolve_label` still
  translates a spaced stem to the member. **Breaking** for any consumer that
  grep-parses these strings: the Android Kotlin mirror, Python tests, docstring
  references and user docs have been updated atomically.

### Added
- **Shared action-label SSOT** (`hsync_common.labels`): the `ActionLabel`
  `StrEnum` (every bracketed log label across the ecosystem), the
  `LABEL_CATEGORIES` semantic-color map, the derived `LABEL_STYLES` view, the
  `colorize_labels` helper (wired into both client and server loguru
  formatters), and `resolve_label` (the single label-resolution helper shared by
  the watchdog handlers and the inbound event dispatcher). Client and server
  now re-export `ActionLabel` from here; no project-local label table remains.
  Labels are grouped into semantic categories (transfer/upload/create/modify/
  rename/delete/permission/in-sync/warning/security/infrastructure) so the log
  output uses a small set of meaningful colors instead of one per label.
- **Runtime environment detection** (`hsync_common.runtime`): container
  detection (`detect_container` → Docker/Podman/Kubernetes/containerd via the
  `container` env var, `/.dockerenv`, `/run/.containerenv`, `/proc/1/cgroup`
  markers), interactive-terminal detection (`is_tty_interactive`), the color
  output gate SSOT (`color_output_enabled`: `--no-color` flag, standard
  `NO_COLOR` env, stdout TTY), cgroup resource introspection
  (`get_memory_limit_bytes` / `get_cpu_quota_cores`, v2 with v1 fallback), and
  `runtime_summary` for one-line startup logs.
- **Delta transfer protocol**: new `delta` capability token in
  `hsync_common.protocol.handshake.Capability`; new `delta` optional key in
  `LAN_TXT_KEYS` (`hsync_common.protocol.schemas`); regenerated `txt-schema.json`
  and `lan-txt-record.json` fixture with `delta: "true"`. Core delta algorithm
  in `hsync_common.delta`: rolling Adler32 checksum, block signatures, find_matches,
  apply_delta. Decision logic in `hsync_common.delta.decision`: optimal block size
  (4/16/64/256 KB thresholds), is_delta_worthwhile (50% change ratio, 1 GB literal
  cap). Constants: `DELTA_MIN_FILE_SIZE` (256 KB), `DELTA_MIN_FILE_SIZE_LAN` (1 MB),
  `DELTA_MAX_CHANGE_RATIO` (0.50), `DELTA_MAX_LITERAL_SIZE` (1 GB), `DELTA_TOKEN_TTL`
  (300 s), `DELTA_BLOCK_SIZE_SMALL/MEDIUM/LARGE/XLARGE`.
- **DeltaApplyMetadata model**: new dataclass and TypedDict in
  `hsync_common/models/delta.py` for POST /delta/apply metadata (upload delta).
  Includes cid, base/new SHA-256, new_size, block_size, compressed flag, ops,
  optional mtime/permissions. Mirrors the wire shape used by the server apply
  endpoint and the Android Kotlin implementation.
- **Delta protocol fixtures**: three new golden fixtures in
  `hsync_common/protocol/fixtures/` for cross-platform parity testing:
  `delta-signatures.json` (example block signatures), `delta-instructions.json`
  (example delta operations), `delta-apply-metadata.json` (example apply
  metadata). These fixtures are consumed by the Android parity tests and can
  be used by future implementations in other languages.
- **ADR-0016**: Delta transfer (rsync-style block sync) — documents the
  architectural decision to implement rsync-style delta transfer for efficient
  synchronization of large files with small changes. Covers the rolling checksum
  algorithm, wire protocol, capability negotiation, size thresholds, fallback
  behavior, and concurrency considerations.

### Security
- `decompress_data` now accepts `max_output_size`, enforcing a hard cap on the
  decompressed size via a capped streaming read (anti decompression-bomb for
  wire-supplied payloads); new `decompress_stream` generator applies the same
  cap to streamed HTTP response bodies
- New wire-facing remote-path validators in `path_validation.py`:
  `validate_remote_relpath` (rejects `..`, absolute paths, drive letters,
  backslashes, forbidden/control characters, Windows reserved names,
  problematic trailing characters and internal engine artifacts),
  `resolve_within` (`resolve()`+`relative_to()` confinement),
  `is_safe_symlink_target` (now the SSOT shared with the server)
- New `INTERNAL_FILENAMES` denylist (`.hsyncignore`, `.hsyncstate`,
  `.hsynctombstones`): `IgnoreMatcher` always excludes them, even with
  `include_hidden=True`, so engine state can no longer be rewritten through
  the sync channel
- New `REMOTE_PERMISSION_MASK` (0o777) and `sanitize_remote_permissions`:
  setuid/setgid/sticky bits are stripped from peer-supplied permission strings
- `TombstoneStore.merge`/`load` now validate untrusted gossip payloads:
  sha256-hex keys/content hashes, rejection of future timestamps beyond a
  300 s clock-skew tolerance, and a 100 000-entry store cap (anti-poisoning)

### Added
- New `security_rejected` structured UI event name, emitted by clients when a
  remote-supplied path is rejected as unsafe
- New `is_valid_cid`/`CID_PATTERN` wire-facing client-ID format validation
  (`models/event.py`)
- New `is_sha256_hex` wire-facing checksum-shape validator (`hashing.py`):
  peer-supplied digests must pass it before `hmac.compare_digest`, which
  raises `TypeError` on non-ASCII input
- New `wire_relpaths`/`WIRE_PATH_KEYS` (`path_validation.py`): SSOT for the
  set of path-carrying keys of an event payload (`filepath`, `path`), used by
  both the server relay gate and the client dispatcher so the key set cannot
  drift between peers

### Fixed
- `is_valid_cid` no longer accepts a trailing newline: Python's `$` also
  matches before a final `\n`, so a cid like `"abc\nForged log line"` passed
  validation; the regex is now applied with `fullmatch`
- `is_safe_symlink_target` no longer crashes on unresolvable targets
  (embedded NUL byte, over-long components): resolution errors now return
  `False` instead of propagating (remote DoS via a crafted symlink event)
- `TombstoneStore.merge` no longer crashes on truthy non-dict payloads (JSON
  array/string), and `TombstoneStore.load` no longer crashes at startup when
  the `"tombstones"` member is not an object
- `TombstoneStore.merge`/`load` no longer crash on non-finite float
  timestamps (`Infinity`/`NaN`, accepted by `json.loads`) — `int()` is now
  guarded against `OverflowError` and raw `bool` values are rejected
- `is_internal_name` matching is now case-insensitive: on case-insensitive
  filesystems (Windows, default macOS) a remote peer can no longer overwrite
  the victim's `.hsyncignore`/`.hsyncstate`/`.hsynctombstones` (or `.part`
  artifacts) through a case variant such as `.HSYNCIGNORE`
- Aligned `aiofiles` constraint to `>=25.1.0,<26.0.0`, resolving the version
  conflict with `hsync-server` (which requires `>=25.1.0`) that made
  `poetry lock` fail for downstream projects
- `IgnoreMatcher._to_relative` now strips only a leading `./` instead of any
  leading dots/slashes, so `.hsyncignore` patterns can match dotfiles again

### Changed
- **Ignore patterns**: vim swap files are now matched only as dotfiles
  (`.*.sw?` replaces `*.swp`/`*.swo` in `DEFAULT_IGNORE_PATTERNS`), so
  non-hidden names such as `animation.swf` are no longer excluded by mistake.
  Real Vim/Neovim swap files (`.file.swp`, `.file.swo`, `.file.swx`) remain
  ignored.
- **Ignore patterns**: GNOME GIO safe-save temp files (`.goutputstream-*`)
  are now in `DEFAULT_IGNORE_PATTERNS`. These transient files are created by
  GNOME editors (gedit, nautilus, …) during atomic safe-save and must never
  be synced; the client's watcher reframes the temp→final rename as a content
  `modified` of the destination file.
- **Ignore patterns**: Chromium-based browser (Chrome, Edge, Brave) in-progress
  download temp files (`*.crdownload`) are now in `DEFAULT_IGNORE_PATTERNS`.
  These files are created during an active download and renamed to the final
  name only when complete; syncing them would propagate a truncated file.
- Updated development dependencies: coverage 7.15.2, filelock 3.31.2,
  platformdirs 4.10.1, ruff 0.15.22
- **Docs**: Updated `CONTRIBUTING.md` — added a test-structure table organised
  by area (protocol, models, path validation, delta, compression, config,
  utils, docs) covering the actual test files, expanded the test command
  examples, and added a cross-project testing section reminding contributors
  to run the downstream `hsync-client` and `hsync-server` suites when changing
  shared models or protocol constants.

## [1.0.0] — 2025-12-xx

### Added
- Initial release: shared foundation for the HSYNC ecosystem
- Canonical data models: `File`, `Dir`, `Symlink`, `Event`, `SyncAction`, `TombstoneEntry`
- Three-way merge algorithm (`resolve_three_way`) and `SyncStateStore`
- Zstandard (zstd) compression utilities with pre-compressed extension detection
- `.hsyncignore` gitignore-style pattern matcher (`IgnoreMatcher`)
- Shared constants, protocol versioning, and handshake utilities
- Path validation and traversal protection
- SSL utilities (self-signed certificate generation, fingerprinting)
- Shared logging configuration and environment-file loading
- Cross-language test fixtures for LAN election and pairing scenarios
- Architecture Decision Records (ADRs)

[1.0.0]: https://github.com/albertobasso/hsync-common/releases/tag/v1.0.0
