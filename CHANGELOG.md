# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- `decompress_data` now accepts `max_output_size`, enforcing a hard cap on the
  decompressed size via a capped streaming read (anti decompression-bomb for
  wire-supplied payloads)
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

### Fixed
- Aligned `aiofiles` constraint to `>=25.1.0,<26.0.0`, resolving the version
  conflict with `hsync-server` (which requires `>=25.1.0`) that made
  `poetry lock` fail for downstream projects
- `IgnoreMatcher._to_relative` now strips only a leading `./` instead of any
  leading dots/slashes, so `.hsyncignore` patterns can match dotfiles again

### Changed
- Updated development dependencies: coverage 7.15.2, filelock 3.31.2,
  platformdirs 4.10.1, ruff 0.15.22

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
