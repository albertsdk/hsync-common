# HSYNC Common Library — Decisions

Ecosystem-wide architectural decisions are recorded as ADRs under
[`../docs/internal/adr/`](../docs/internal/adr/README.md) (committed, human-readable). They are the
*why* behind the SSOT this library exposes. This page is the agent index mapping
each ADR to the code it governs.

| ADR | Governs (code) |
| --- | -------------- |
| [0001 server-vs-lan-modes](../docs/internal/adr/0001-server-vs-lan-modes.md) | client run modes; LAN stack vs REST stack |
| [0002 lan-master-election](../docs/internal/adr/0002-lan-master-election.md) | `protocol/lan.py:67` (`election_sort_key`, `elect_master`) |
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
| [0017 lan-slave-outbound-event-reliability](../docs/internal/adr/0017-lan-slave-outbound-event-reliability.md) | `hsync_client/lan_websocket.py` (defer-to-close, echo-pair cache); Android mirror |
| [0018 origin-based-log-labels](../docs/internal/adr/0018-origin-based-log-labels.md) | `labels.py` (`ActionLabel`, `resolve_label`, `LOCAL`/`REMOTE` prefix); Kotlin mirror `LogManager.kt` |
| [0020 lan-security-model](../docs/internal/adr/0020-lan-security-model.md) | `protocol/pairing.py` (pairing); `ssl_utils.py` (self-signed cert); `hsync_client/pinning.py` (TOFU pinning); Android `PinStore.kt` |
| [0022 causal-vector-clock-conflict-model](../docs/internal/adr/0022-causal-vector-clock-conflict-model.md) | `models/version.py` (`resolve_three_way`, `compare_vclocks`, `tick_vclock`, `merge_vclocks`) + `models/version_store.py` (`SyncStateStore`); `Capability.vector_clocks`; `FileDict.version` |
| [0023 corrected-mtime-tie-break](../docs/internal/adr/0023-corrected-mtime-tie-break.md) | `clock.py` (HTTP/RTT + SNTP multi-host probes, `ClockOffsetStore`/`correct_mtime`, `clamp_wire_corrected_mtime`); `constants.py` (`NTP_DEFAULT_HOSTS`, skew guard); `models/version.py` (`corrected_mtime` fields + tie-break in `resolve_three_way`); `HSYNC_NTP_HOSTS` env var (WD OS5 packaging) |
| [0024 capability-negotiation](../docs/internal/adr/0024-capability-negotiation.md) | `protocol/handshake.py` (LAN WSS handshake frames); `protocol/schemas.py` (`build_lan_wss_schema`); `hsync_client/capabilities.py` (`local_capabilities`/`adopt_remote_capabilities`); `hsync_client/lan_websocket.py` (WSS auth/hello); `hsync_client/lan.py` (TXT `vector_clocks`/`tombstones`); `hsync_server/api/events.py` (honest reply caps) |
| [0025 sqlite-external-state-store](../docs/internal/adr/0025-sqlite-external-state-store.md) | `models/folder.py` (`.hsyncfolder` marker, `default_state_dir`); `models/sqlstore.py` (`StateDb`, WAL+FULL, `auto_vacuum=INCREMENTAL`, `vacuum()`/`incremental_vacuum()` + `vacuum_state_db`/`incremental_vacuum_state_db` maintenance); `models/version_store.py` / `models/tombstone_store.py` (SQLite-backed stores); `path_validation.INTERNAL_FILENAMES` (`.hsyncfolder` + legacy rejection); consumers `hsync_server/state_maintenance.py` + `hsync_client/state_maintenance.py` |
| [0026 permission-special-bits-policy](../docs/internal/adr/0026-permission-special-bits-policy.md) | `permissions.py` (`PERMISSION_MASK=0o7777` read/serialize, `REMOTE_PERMISSION_MASK=0o777` + `OWNER_DIRECTORY_ACCESS=0o700` apply); client `utils.py` `set_permissions`/`set_permissions_on_dir`; server `api/utils.py` `set_permissions`/`set_directory_permissions`; tests `test_permissions.py`, `test_security_inbound.py` |
| [0027 lan-leadership-lease](../docs/internal/adr/0027-lan-leadership-lease.md) | `labels.py` (`ActionLabel.MASTER_YIELD`); client `lan.py` `LANSync.update_server_not_ready` + `lan_handler.py` yield path (revoke incumbency on yield) |

LAN transport/security specifics (TOFU pinning, LAN-key policy, threat model)
live in [`../docs/lan-protocol.md`](../docs/lan-protocol.md) and map to
`protocol/pairing.py` + `ssl_utils.py`.

## House rules (from `CLAUDE.md`)

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
