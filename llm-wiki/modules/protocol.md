# HSYNC Common Library — `protocol/` package

Versioned wire contract + generators. This is the SSOT; never redefine these
constants in consumers.

## handshake.py — versions, capabilities, WS + p2p-WSS auth

| Symbol | Location | Purpose |
| ------ | -------- | ------- |
| `PROTOCOL_VERSION_REST/WS/P2P` | `protocol/handshake.py::PROTOCOL_VERSION_REST` | `api/1`, `ws/1`, `p2p/1` |
| `Capability` (StrEnum) | `protocol/handshake.py::Capability` | feature tokens; `ALL_CAPABILITIES` `protocol/handshake.py::ALL_CAPABILITIES`; includes `delta`, `vector_clocks`, and p2p `peer_download` (ADR-0028) |
| `encode_capabilities` / `decode_capabilities` | `protocol/handshake.py::encode_capabilities` | tokens ⇄ enum set |
| `WsAuthRequest` / `WsAuthResponse` TypedDicts | `protocol/handshake.py::WsAuthRequest` | WS auth frames |
| `WsPresenceFrame` / `build_ws_presence` | `protocol/handshake.py::WsPresenceFrame` | server → client presence frame (connected/total) |
| `build_ws_auth_request` | `protocol/handshake.py::build_ws_auth_request` | client/android → server (protocol_version, app_version, capabilities, token) |
| `build_ws_auth_ok` / `build_ws_auth_error` | `protocol/handshake.py::build_ws_auth_ok` | server → client (ok lists server caps; error carries client_protocol_version) |
| `P2PAuthRequiredFrame` / `P2PAuthFrame` / `P2PAuthResultFrame` / `P2PHelloFrame` | `protocol/handshake.py::P2PAuthRequiredFrame` | p2p master⇄slave handshake TypedDicts (ADR-0024) |
| `build_p2p_auth_required` / `build_p2p_auth` / `build_p2p_auth_ok` / `build_p2p_auth_failed` / `build_p2p_hello` | `protocol/handshake.py::build_p2p_auth_required` | p2p-WSS frame builders: greeting, auth frame (+token/cid), ok/failed replies, hello (both directions) |

Strict policy: a protocol-version mismatch is a **hard fail** (server replies
error / 426; peers disconnect / auth refused). Capabilities are feature flags
within a version — intersection semantics, never cross-version negotiation
(ADR-0024).

## bootnode.py — `boot/1` bootstrap mirror (ADR-0032, ADR-0033)

Mirror of the canonical `boot/1` contract (`hsync-bootnode/protocol-spec/boot-1.md`
+ `hsync-bootnode/fixtures/`). The daemon keeps its own frame models and does not
import this mirror; its Python v1 reuses only generic `hsync-common` utilities
(`ssl_utils`, `CID_PATTERN`, `is_valid_bucket_name` — ADR-0033).

- `PROTOCOL_VERSION_BOOT = "boot/1"` (`protocol/bootnode.py::PROTOCOL_VERSION_BOOT`), `BOOT_ALPN = "hsync-boot/1"`.
  The default listener port is `BOOT_DEFAULT_PORT = 443`
  (`hsync_common/constants.py`, next to `NTP_PORT`) — consumers: hsync-bootnode
  CLI `--port` default and hsync-client bare-host default.
- TypedDict frames + strict `validate_*` validators (dependency-free, like the
  rest of the package): `BootRegister` / `BootRefresh` / `BootLeave` /
  `BootQuery` (client→server) and `BootAck` / `BootResponse` / `BootPeer`
  (server→client); `validate_boot_frame` dispatches on `type`.
- `CAPACITY_MAX = 32` bounds the advisory service-capacity hint (`0` = not a
  seeder); `reachable` is derived from `bool(endpoints)`. `BootPeer.endpoints`
  mirrors the peer's full advertised candidate list (relayed verbatim by the
  node, or a single-element observed-source fallback), so the client can prefer
  a host/LAN candidate over the NATed public one.
- Token helpers: `derive_bucket_token` (`HMAC-SHA256(key, "boot/1"||bucket)`),
  `is_valid_bucket_token`, `constant_time_equals`, `verify_bucket_token`. The
  implementation (and the 64-hex grammar) is the protocol-neutral
  `protocol/boot_tokens.py` (`boot_tokens.py::derive_bucket_token`), shared with
  the bootnode daemon and re-exported here so the client import path is stable.
- Fixture mirror `protocol/fixtures/bootnode-*.json` is byte-checked against the
  canonical bootnode fixtures by `tests/test_protocol_bootnode.py`.
- Consumers: `hsync-client` (bootnode discovery), shared fixtures/tests.

## capabilities.py — `--capabilities-json` document

- `CAPABILITIES_SCHEMA_VERSION = 1` (`protocol/capabilities.py::CAPABILITIES_SCHEMA_VERSION`); the desktop accepts
  only this version.
- `ProtocolVersions` (`protocol/capabilities.py::ProtocolVersions`) carries `rest`, `ws`, `p2p`, `boot`;
  `CapabilitiesDoc` (`protocol/capabilities.py::CapabilitiesDoc`) is the document TypedDict.
- `build_capabilities` (`protocol/capabilities.py::build_capabilities`) aggregates the supported subcommands, the
  per-subcommand CLI option flags, the protocol versions and the events schema
  version.
- `parse_capabilities` (`protocol/capabilities.py::parse_capabilities`) accepts only the current schema version and rejects missing keys
  **and** wrong field types (`_field_types_valid` `protocol/capabilities.py::_field_types_valid`; the document crosses a
  process boundary, so a malformed `subcommands`/`cli_options`/`capabilities`
  must be refused, not mis-parsed).
- `supports_cli_option` (`protocol/capabilities.py::supports_cli_option`, scoped to one subcommand or on the union of
  all) and `supports_subcommand` (`protocol/capabilities.py::supports_subcommand`) back the desktop gating. Emitted by
  the client `--capabilities-json` global flag, consumed by desktop to
  enable/disable controls.

## events.py — UI/telemetry event stream

- `EVENTS_SCHEMA_VERSION = 1` (`protocol/events.py::EVENTS_SCHEMA_VERSION`).
- `UiEventName` StrEnum (`protocol/events.py::UiEventName`) — the structured events emitted by the
  client and consumed by desktop/android (incl. `sync_paused`,
  `transfer_failed`, `fingerprint_changed`, `auth_required`, `pairing_needed`,
  `duplicate_identity`, `security_rejected`, `discovery`, `no_master`, `no_peers`,
  `folder_size`).
- `no_peers` is emitted by the client when a p2p one-shot aborts because no peer
  was discovered (`P2P_NO_PEER`).
- `folder_size` carries `local_bytes` (files present on this device) and
  `total_bytes` (remote/master listing sizes plus local-only files pending
  upload). The client emits it once per distinct pair after fetching its
  listings; full-share runs only (scoped runs skip it), so a GUI can show the
  shared folder's size without a second disk walk.
- `discovery` carries `plan` (`mdns` | `mdns+bootnode`) and, with the bootnode plan,
  the `bootnode` host: the client emits it once at `hsync p2p` startup so a GUI
  can surface the active discovery plan instead of silently degrading to mDNS.
  The payload is a flat optional-field object; `parse_event_line` ignores
  unknown event names.
- `progress` carries `file`, `transferred`, `total` and `op` (`download` |
  `upload`). The throttled progress of every in-flight transfer — received
  files included — is how a GUI learns about a file that is not on disk yet;
  consumers must use `op` to decide the direction instead of assuming one.
- `UiEventDict` (`protocol/events.py::UiEventDict`) includes optional `source_cid` only for a
  successful verified peer-served full download; build/serialize/parse:
  `build_event` (`protocol/events.py::build_event`), `serialize_event` (`protocol/events.py::serialize_event`),
  `parse_event_line` (`protocol/events.py::parse_event_line`).

## p2p.py — p2p wire SSOT (master election + p2p-only paths)

- Realtime control-plane path: `P2P_WS_EVENTS_PATH` (`protocol/p2p.py::P2P_WS_EVENTS_PATH`) template and
  `p2p_ws_events_path(bucket, cid)` (`protocol/p2p.py::p2p_ws_events_path`); the master registers the
  template, the client builds the concrete path, and the Android mirror
  (`PeerDownloadContracts.kt`) matches it. The bucket prefix comes from
  `protocol.rest`.
- p2p-only endpoint `P2P_FILES_SOURCES_SUFFIX` (`protocol/p2p.py::P2P_FILES_SOURCES_SUFFIX`): source resolution
  has no hsync-server counterpart; its concrete path is built with
  `rest_bucket_path`.
- `ElectionCandidate` dataclass (`protocol/p2p.py::ElectionCandidate`).
- Ordering key `election_sort_key` (`protocol/p2p.py::election_sort_key`); SSOT ranking
  `rank_election_candidates` (`protocol/p2p.py::rank_election_candidates`) returns the full ranked list
  (never_master filtered out); `elect_master` (`protocol/p2p.py::elect_master`) is its
  winner-only projection; `SYNC_DIRECTION_BIDIRECTIONAL` (`protocol/p2p.py::SYNC_DIRECTION_BIDIRECTIONAL`).
- The client `hsync_client/p2p_peers.py` consumes `rank_election_candidates` for
  master, successor and the prefer_master conflict subset; android
  `Election.kt` mirrors the ordering; parity is pinned by the
  `p2p-election-scenarios` fixture.

## rest.py — REST surface SSOT (paths shared with hsync-server)

- `REST_API_PREFIX` (`protocol/rest.py::REST_API_PREFIX`), service paths (`REST_HEALTH_PATH`
  `protocol/rest.py::REST_HEALTH_PATH`,
  `REST_METRICS_PATH`, `REST_TIME_PATH`) and the admin surface.
- `REST_BUCKETS_PREFIX` (`protocol/rest.py::REST_BUCKETS_PREFIX`) plus the `REST_*_SUFFIX` constants
  (`protocol/rest.py::REST_BUCKETS_PREFIX`), with `rest_bucket_base` (`protocol/rest.py::rest_bucket_base`),
  `rest_bucket_path` (`protocol/rest.py::rest_bucket_path`),
  `rest_bucket_template` (`protocol/rest.py::rest_bucket_template`) and `rest_delta_data_path`
  (`protocol/rest.py::rest_delta_data_path`).
- `REST_PATH_TEMPLATES` (`protocol/rest.py::REST_PATH_TEMPLATES`) is the whole named surface, compared
  **byte-for-byte** with the committed OpenAPI snapshot (`protocol/__init__.py::REST_OPENAPI_PATH`) by
  `tests/test_protocol_rest.py`; a server route change fails that test until
  this module is updated, so clients cannot drift.
- Consumers: `hsync-client` (server API requests, peer-download mirror) and the
  Android mirror (`PeerDownloadContracts.kt`).

## pairing.py — TOFU pin + p2p-key policy

- `PinDecision` StrEnum (`protocol/pairing.py::PinDecision`); `normalize_fingerprint`
  (`protocol/pairing.py::normalize_fingerprint`); `evaluate_pin` (`protocol/pairing.py::evaluate_pin`).
- Bootnode trust primitives (ADR-0034): `parse_fingerprint` (`protocol/pairing.py::parse_fingerprint`)
  normalizes `sha256:<hex>` / bare hex to lowercase 64-char hex (rejects invalid),
  `fingerprint_matches` (`protocol/pairing.py::fingerprint_matches`) compares constant-time against a pin
  set, `FingerprintMismatch` (`protocol/pairing.py::FingerprintMismatch`) is the shared fatal-exception.
  Consumers: `hsync-client` bootnode pinning; future Rust/Android parity.
- `requires_pairing_confirmation` (`protocol/pairing.py::requires_pairing_confirmation`) — strict out-of-band pairing.
- `is_write_direction` (`protocol/pairing.py::is_write_direction`) + `p2p_write_requires_key`
  (`protocol/pairing.py::p2p_write_requires_key`); write directions set `protocol/pairing.py::_WRITE_DIRECTIONS`. ADR-0029 makes every
  write-capable run require a key unless the explicit dangerous
  `allow_unauthenticated_writes` opt-in is set.

## peer_download.py — strict p2p peer-download wire contract

- Payload TypedDicts cover batch source request/response candidates,
  snapshot/delta inventory entries and frames, and cumulative ACKs
  (`protocol/peer_download.py::validate_p2p_sources_request`).
- `validate_p2p_sources_request` / `validate_p2p_sources_response` and matching
  builders enforce exact keys, canonical normalized paths, lowercase hashes,
  CID/candidate uniqueness, IP-literal HTTPS endpoints, 500-file/8-candidate
  limits, and the 2 MiB compact-payload ceiling (`protocol/peer_download.py::validate_p2p_sources_request`).
- `validate_p2p_inventory_frame` / `validate_p2p_inventory_ack` and matching
  builders enforce mode-specific entries, non-boolean signed-64-bit counters,
  duplicate-path rejection, terminal empty snapshots, strict ACK reasons, and
  the shared 2 MiB/500-entry bounds (`protocol/peer_download.py::validate_p2p_inventory_frame`).

## schemas.py — JSON-Schema builders (draft 2020-12)

- Dialect const `protocol/schemas.py::JSON_SCHEMA_DIALECT`; p2p TXT key sets
  `protocol/schemas.py::P2P_TXT_REQUIRED_KEYS`/`protocol/schemas.py::P2P_TXT_OPTIONAL_KEYS`/`protocol/schemas.py::P2P_TXT_KEYS` include the
  optional `peer_download` implementation flag. Live seeder capacity is not a TXT
  fact: it travels on the authenticated handshake (ADR-0030).
- `build_ws_schema` (`protocol/schemas.py::build_ws_schema`), `build_p2p_wss_schema` (`protocol/schemas.py::build_p2p_wss_schema`; pins
  auth/hello plus inventory/ACK frames, ADR-0024/0028),
  `build_p2p_sources_schema` (`protocol/schemas.py::build_p2p_sources_schema`), and `build_p2p_txt_schema`
  (`protocol/schemas.py::build_p2p_txt_schema`) derive
  enums/objects and bounds from `handshake`, `peer_download`, `events`, and the
  `models/` types. Shared capabilities-array schema is `_capabilities_array`.

## fixtures.py — cross-language golden fixtures

- `build_fixtures` (`protocol/fixtures.py::build_fixtures`) assembles file-event, master/seeder p2p TXT,
  peer source request/response, inventory/ACK, election, pin/write-policy,
  pairing and causal scenarios from the SSOT builders.
- The **delta fixtures** (`delta-signatures`, `delta-instructions`,
  `delta-apply-metadata`) are generated by the real matching engine
  (`_delta_example`: 1 MB LCG base, 4 KB blocks, block 1 replaced) via
  `delta.signatures_for_data` + `find_matches`, so `sum(op.length) ==
  new_size` holds by construction and the apply-metadata keys are exactly
  `DeltaApplyMetadata.to_dict()` — no hand-written numbers. Pinned by
  `TestDeltaFixtureCoherence` in `test_protocol_fixtures.py`.
- Consumed by Python drift tests and copied into Android test resources for
  parity (`test_protocol_schemas.py`, android `ProtocolContractTest`).

## __init__.py — paths & (de)serialization

- Artifact path constants: `REST_OPENAPI_PATH` (`protocol/__init__.py::REST_OPENAPI_PATH`),
  `WS_SCHEMA_PATH` (`protocol/__init__.py::WS_SCHEMA_PATH`),
  `P2P_TXT_SCHEMA_PATH` (`protocol/__init__.py::P2P_TXT_SCHEMA_PATH`),
  `P2P_WSS_SCHEMA_PATH` (`protocol/__init__.py::P2P_WSS_SCHEMA_PATH`),
  `P2P_SOURCES_SCHEMA_PATH` (`protocol/__init__.py::P2P_SOURCES_SCHEMA_PATH`),
  `FIXTURES_DIR` (`protocol/__init__.py::FIXTURES_DIR`),
  `BOOTNODE_FIXTURES_DIR` (`protocol/__init__.py::BOOTNODE_FIXTURES_DIR`),
  `ANDROID_FIXTURES_DIR` (`protocol/__init__.py::ANDROID_FIXTURES_DIR`).
- Canonical dump/load: `dump_contract`/`load_contract` (`protocol/__init__.py::dump_contract`),
  with `dump_openapi` (`protocol/__init__.py::dump_openapi`) reusing them.

## Change checklist

Editing any of the above ⇒ rerun `scripts/export_protocol_schemas.py`
(+ `hsync-server/scripts/export_openapi.py` for REST), regenerate fixtures, and confirm
`tests/test_protocol_schemas.py` / `test_capabilities.py` stay green. Update the
Kotlin mirrors (`Protocol.kt`, `Election.kt`, `Pairing.kt`) in the same change.

> Decision rationale (versioning, election, tombstones, conflict model):
> [../decisions.md](../decisions.md) → `../../docs/internal/adr/`.
