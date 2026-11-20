# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The `readonly_permissions` capability
  (`hsync_common/protocol/handshake.py::Capability`) marks a node whose local
  filesystem represents only the owner-write bit; absence means full POSIX modes.
  The P2P TXT SSOT declares the matching `readonly_permissions` flag
  (`hsync_common/protocol/schemas.py::P2P_TXT_OPTIONAL_KEYS`), so a Windows
  node's mDNS record validates against the published schema.
- TLS trust policy `auto` (`hsync_common/protocol/tls_trust.py::TrustPolicy.auto`
  and `resolve_auto_policy`): prefer a stored pin, then standard CA validation,
  then trust-on-first-use; `evaluate_tls_trust` refuses an unresolved `auto`
  (ADR-0051).
- The installation DB keeps a node-global monotonic clock counter
  (`counters` table, `StateDb.next_counter`/`raise_counter`): every persisted
  version and tombstone raises the floor, so a node can never mint a counter it
  already published — the node-scope anti-aliasing invariant (ADR-0022 §6).
- `set_sha256_cache_provider` / `reset_sha256_cache_provider`
  (`hsync_common/models/file.py`): a host can route `File.get`'s checksum cache
  to a cache it already owns, so the server listing shares its preloaded
  `FILE_HASHES` instead of hashing into the 10k client LRU.
- `file_entry(..., rel=...)` (`hsync_common/listing.py::file_entry`) accepts the
  already-resolved bucket-relative path, so a caller that also needs it for the
  version JOIN does not compute it twice.

### Changed

- Path identity is independent of the host separator and Unicode form:
  `_split_path_components`/`_strip_prefix_components`
  (`hsync_common/models/_util.py`) split on `/` and `\` and compare
  NFC-normalized components, so a listing produced on Windows keys the same
  local state as one produced on Linux and an NFD macOS name matches its NFC
  peer.
- The permission model maps a lossy host instead of rejecting it: on Windows
  `get_permissions` reports the canonical `644`/`755` pair (`444`/`555` when
  read-only) and `apply_remote_permissions` writes or clears only the Read-only
  attribute; `has_owner_write` and `local_permissions_are_lossy`
  (`hsync_common/permissions.py`) expose the portable bit and the host's
  lossiness. The mapping is one function
  (`canonical_permissions`) so the `File`/`Dir` metadata paths a peer reads emit
  the same canonical modes instead of the synthetic NTFS `666`/`777`.
- The ignore matcher serves the literal default names from a set when no custom
  pattern exists (~9 fewer regexes per scanned entry); a `.hsyncignore` or an
  extra pattern still compiles the full spec, so negations keep working.

### Fixed

- `iter_json_array` (`hsync_common/listing.py`) batches its output (64 KiB):
  `StreamingResponse` dispatches one worker-thread hop per yielded chunk, so one
  fragment per entry dominated a large listing. The JSON bytes are unchanged
  and peak memory stays O(batch + one entry).
- Symlink replication on Windows no longer skips in-bucket links: the
  `\\?\`/`\\?\UNC\` extended-length form that `readlink`/`resolve` can return is
  compared without its prefix, a target carrying an embedded NUL is rejected, and
  the wire target always uses POSIX separators (a backslash would be a literal
  filename character on every other peer).
- `is_valid_filename` (`hsync_common/path_validation.py`) enforces the 255-byte
  component cap its portable-name policy already documented, so an overlong name
  is refused instead of reaching the filesystem write (`ENAMETOOLONG`).
- A `.hsynckeep` marker left behind in a directory that later received content is
  dropped again (`hsync_common/models/sentinel.py::prune_sentinel`), and the
  marker's emptiness rule is exposed read-only
  (`hsync_common/models/sentinel.py::dir_has_syncable_entry`) so a status pass can
  consult it without creating anything.

## [1.1.0] - 2026-11-11

### Added

- The `activity` UI event reports the data-movement phase (`syncing`/`idle`)
  on its own axis: `status` carries the link state only, so a cycle running on
  a live link leaves it `connected`.
- The `rdv/1` rendezvous channel is transport-neutral in the shared code:
  `RDV_TRANSPORTS`, `RDV_TRANSPORT_DEFAULT`, `RDV_TRANSPORT_STAGGER_S` and
  `RDV_TCP_FALLBACK_TTL_S` name the QUIC/UDP and TLS/TCP options, and
  `hsync_common.tls_context` provides the certificate-free client TLS context
  without pulling `cryptography` into the CLI startup path.
- The `X-Client-Id` request header constant (`HEADER_CLIENT_ID`), carrying the
  requester CID so the P2P master can bucket relayed peers (which all arrive
  from the loopback address) by identity.

### Changed

- The master election prefers a node that confirms an externally dialable
  endpoint (`inbound`); the mDNS TXT schema and the `rdv/1` register/peer
  mirrors carry it, and a reachable node out-ranks a relay-only one.
- The data-relay docs (ADR-0047, `rdv-protocol.md`) state that the peers
  multiplex their loopback connections inside the opaque relay stream, which the
  node never parses.

### Fixed

- The wiki anchor checker accepts a `file.py::Class.attribute` anchor that
  points at a bare annotated declaration (`_link_down: bool`) or at a
  `self.x = ...` assignment instead of reporting it as a broken anchor.
