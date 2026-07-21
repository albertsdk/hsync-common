# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Aligned `aiofiles` constraint to `>=25.1.0,<26.0.0`, resolving the version
  conflict with `hsync-server` (which requires `>=25.1.0`) that made
  `poetry lock` fail for downstream projects

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
