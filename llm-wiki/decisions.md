# HSYNC Common Library — Decisions

Ecosystem-wide architectural decisions are recorded as ADRs under
[`../docs/internal/adr/`](../docs/internal/adr/README.md) (committed, human-readable). They are the
*why* behind the SSOT this library exposes. This page is the agent index mapping
each ADR to the code it governs.

| ADR | Governs (code) |
| --- | -------------- |
| [0001 server-vs-p2p-modes](../docs/internal/adr/0001-server-vs-p2p-modes.md) | client run modes; LAN stack vs REST stack |
| [0002 p2p-master-election](../docs/internal/adr/0002-p2p-master-election.md) | `protocol/p2p.py:67` (`election_sort_key`, `elect_master`) |
| [0003 tombstone-gossip](../docs/internal/adr/0003-tombstone-gossip.md) | `models/tombstone.py` (`tombstone_merge_decision`, hashed keys, TTL 90 storage GC) + `models/tombstone_store.py` (`TombstoneStore` causal merge) |
| [0004 desktop-subprocess-contract](../docs/internal/adr/0004-desktop-subprocess-contract.md) | `protocol/events.py` event stream; `protocol/capabilities.py` |
| [0005 protocol-versioning](../docs/internal/adr/0005-protocol-versioning.md) | `protocol/handshake.py:44` (versions + hard-fail handshake) |
| [0007 integrity-verification](../docs/internal/adr/0007-content-addressed-storage.md) | `hsync_server/hashes.py` (`FILE_HASHES`: `SHA256(filepath)→SHA256(content)`, idempotent upload detection); `models/file.py` (content hash model) |
| [0008 client-accounts](../docs/internal/adr/0008-client-accounts.md) | `hsync_server/auth.py` + `auth_store.py` (account tokens, roles, bucket membership); server-only, common defines no auth code |
| [0009 rest-websocket-transport](../docs/internal/adr/0009-rest-websocket-transport.md) | `protocol/schemas.py` (REST schema SSOT); `protocol/ws/ws-schema.json` (WS schema); `hsync_server` implements endpoints |
| [0010 zstandard-compression](../docs/internal/adr/0010-zstandard-compression.md) | `compression.py` (adaptive thresholds, precompressed extension list) |
| [0011 resumable-upload](../docs/internal/adr/0011-resumable-upload.md) | `hsync_server/api/files/upload.py` (Content-Range, `.partial` temp files, atomic rename) |
| [0012 rate-limiting](../docs/internal/adr/0012-rate-limiting.md) | `hsync_server/rate_limiter.py` (slowapi token-bucket, per-IP tiers) |
| [0013 hsyncignore-gitignore-syntax](../docs/internal/adr/0013-hsyncignore-gitignore-syntax.md) | `ignore.py` (`load_hsyncignore`, `pathspec.PathSpec`) |
| [0014 multi-repo-strategy](../docs/internal/adr/0014-multi-repo-strategy.md) | this repository is the SSOT; enforced by path dependencies, golden fixtures, ADR index |
| [0015 mass-deletion-guard](../docs/internal/adr/0015-mass-deletion-guard.md) | `hsync_client/sync.py` (`_mass_deletion_blocked`); client-side guard, common has no code |
| [0016 delta-transfer](../docs/internal/adr/0016-delta-transfer.md) | `delta/decision.py` (Adler32 + SHA-256 matching); `delta/rolling_checksum.py`; `models/delta.py` (wire shapes) |
| [0017 p2p-slave-outbound-event-reliability](../docs/internal/adr/0017-p2p-slave-outbound-event-reliability.md) | `hsync_client/p2p_websocket.py` (defer-to-close, echo-pair cache); Android mirror |
| [0018 origin-based-log-labels](../docs/internal/adr/0018-origin-based-log-labels.md) | `labels.py` (`ActionLabel`, `resolve_label`, `LOCAL`/`REMOTE` prefix); Kotlin mirror `LogManager.kt` |
| [0020 p2p-security-model](../docs/internal/adr/0020-p2p-security-model.md) | `protocol/pairing.py` (pairing); `ssl_utils.py` (self-signed cert); `hsync_client/pinning.py` (TOFU pinning); Android `PinStore.kt`; unauthenticated-write policy superseded by ADR-0029 |
| [0022 causal-vector-clock-conflict-model](../docs/internal/adr/0022-causal-vector-clock-conflict-model.md) | `models/version.py` (`resolve_three_way`, `compare_vclocks`, `tick_vclock`, `merge_vclocks`) + `models/version_store.py` (`SyncStateStore`); `Capability.vector_clocks`; `FileDict.version` |
| [0023 corrected-mtime-tie-break](../docs/internal/adr/0023-corrected-mtime-tie-break.md) | `clock.py` (HTTP/RTT + SNTP multi-host probes, `ClockOffsetStore`/`correct_mtime`, `clamp_wire_corrected_mtime`); `constants.py` (`NTP_DEFAULT_HOSTS`, skew guard); `models/version.py` (`corrected_mtime` fields + tie-break in `resolve_three_way`); `HSYNC_NTP_HOSTS` env var (WD OS5 packaging) |
| [0024 capability-negotiation](../docs/internal/adr/0024-capability-negotiation.md) | `protocol/handshake.py` (p2p WSS handshake frames); `protocol/schemas.py` (`build_p2p_wss_schema`); `hsync_client/capabilities.py` (`local_capabilities`/`adopt_remote_capabilities`); `hsync_client/p2p_websocket.py` (WSS auth/hello); `hsync_client/p2p.py` (TXT `vector_clocks`/`tombstones`); `hsync_server/api/events.py` (honest reply caps) |
| [0025 sqlite-external-state-store](../docs/internal/adr/0025-sqlite-external-state-store.md) | `models/folder.py` (`.hsyncfolder` marker, `default_state_dir`); `models/sqlstore.py` (`StateDb`, WAL+FULL, `auto_vacuum=INCREMENTAL`, `vacuum()`/`incremental_vacuum()` + `vacuum_state_db`/`incremental_vacuum_state_db` maintenance); `models/version_store.py` / `models/tombstone_store.py` (SQLite-backed stores); `path_validation.INTERNAL_FILENAMES` (`.hsyncfolder` + legacy rejection); consumers `hsync_server/state_maintenance.py` + `hsync_client/state_maintenance.py` |
| [0026 permission-special-bits-policy](../docs/internal/adr/0026-permission-special-bits-policy.md) | `permissions.py` (`PERMISSION_MASK=0o7777` read/serialize, `REMOTE_PERMISSION_MASK=0o777` + `OWNER_DIRECTORY_ACCESS=0o700` apply); client `utils.py` `set_permissions`/`set_permissions_on_dir`; server `api/utils.py` `set_permissions`/`set_directory_permissions`; tests `test_permissions.py`, `test_security_inbound.py` |
| [0027 p2p-leadership-lease](../docs/internal/adr/0027-p2p-leadership-lease.md) | `labels.py` (`ActionLabel.MASTER_YIELD`); client `p2p.py` `LANSync.update_server_not_ready` + `p2p_handler.py` yield path (revoke incumbency on yield) |
| [0028 p2p-peer-assisted-download](../docs/internal/adr/0028-p2p-peer-assisted-download.md) | `protocol/peer_download.py` (strict source/inventory wire models); `protocol/schemas.py` (sources + additive p2p WSS schemas); `Capability.peer_download`; TXT `peer_download`; `constants.HEADER_CHECKSUM_SHA256`; optional UI-event `source_cid` |
| [0029 explicit-opt-in-unauthenticated-p2p-writes](../docs/internal/adr/0029-explicit-opt-in-unauthenticated-p2p-writes.md) | `protocol/pairing.py` (`p2p_write_requires_key`: explicit opt-in, interactivity is non-authoritative); LAN mutation endpoint policy in consumers |
| [0030 p2p-seeder-capacity-advertisement](../docs/internal/adr/0030-p2p-seeder-capacity-advertisement.md) | `protocol/peer_download.py` (`P2P_SERVE_SLOTS_MIN`/`_MAX`, `is_valid_serve_slots`, required `serve_slots` in `P2PSourceCandidate`); `protocol/handshake.py` (`build_p2p_auth`/`build_p2p_hello` advertisement); `protocol/schemas.py` (candidate + p2p WSS schemas); golden fixtures |
| [0034 bootnode-tls-trust](../docs/internal/adr/0034-bootnode-tls-trust.md) | `protocol/pairing.py` (`parse_fingerprint`, `fingerprint_matches`, `FingerprintMismatch`); `ssl_utils.py` (Ed25519 identity); `hsync-bootnode` (opt-in `--identity` persistence) + `hsync-client` (`bootnode_trust.py` pin/TOFU) |

LAN transport/security specifics (TOFU pinning, LAN-key policy, threat model)
live in [`../docs/p2p-protocol.md`](../docs/p2p-protocol.md) and map to
`protocol/pairing.py` + `ssl_utils.py`.

## House rules (from `AGENTS.md`)

- **Zero backward compatibility**: no shims/migration layers; consumers import
  `hsync_common.*` directly.
- **SSOT discipline**: protocol constants, election, pairing and models are
  defined only here; other repos mirror, never fork.
- New ADRs: copy [`../docs/internal/adr/template.md`](../docs/internal/adr/template.md), add to the
  ADR index and reference the governed code here.

## Accepted residual risks

- **TOCTOU window in `resolve_within` → `open`** (path confinement): symlink
  resolution happens at validation time, the file is opened afterwards, so a
  symlink swapped in between could redirect the write. Mitigations in place:
  `.part` downloads open with `O_NOFOLLOW` where supported
  (`hsync-client` `transfer.py`), which covers the final path component but not
  intermediate directories. Exploiting the window requires an attacker who can
  already mutate the victim's local filesystem inside the bucket (a local
  process or a second sync engine racing the first) — at which point the
  integrity checks (mandatory SHA-256 before the atomic rename) still bound the
  damage to wasted work, not corrupted sync content. Accepted as residual risk;
  a full fix would require `openat2(RESOLVE_BENEATH)`-style resolution at open
  time, which is Linux-only and out of scope for the portable validator.

## 2026-10-09 — `p2p/1` rename, capabilities v3, `boot/1` mirror (ADR-0032)

- **Nomenclature**: the data-plane contract carries the `p2p/1` version suffix
  (`PROTOCOL_VERSION_P2P`), `ProtocolVersions.p2p`, `P2P_TXT_KEYS`,
  `p2p_write_requires_key`, `protocol/lan/` → `protocol/p2p/`, fixtures
  `lan-*.json` → `p2p-*.json`, `docs/lan-protocol.md` → `docs/p2p-protocol.md`,
  `Lan*` protocol classes → `P2P*`, `LAN_*` bounds → `P2P_*`. `LAN` survives only
  as a technology name (mDNS/Zeroconf/local area network) and in prose.
- **Capabilities v3**: `CAPABILITIES_SCHEMA_VERSION = 3`; `ProtocolVersions`
  gains `boot`; `parse_capabilities` requires all four channels. The desktop
  rejects any other schema version outright, so this is an atomic boundary.
- **`boot/1` mirror**: canonical spec/fixtures stay in `hsync-bootnode`;
  `hsync_common/protocol/bootnode.py` mirrors the frames (TypedDicts + strict
  `validate_*` helpers, dependency-free like the rest of the package) and the
  token helpers; the mirrored fixtures are drift-tested byte-for-byte against
  `hsync-bootnode/fixtures/`.
