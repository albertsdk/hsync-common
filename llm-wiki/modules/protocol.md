# HSYNC Common Library — `protocol/` package

Versioned wire contract + generators. This is the SSOT; never redefine these
constants in consumers.

## handshake.py — versions, capabilities, WS + p2p-WSS auth

| Symbol | Line | Purpose |
| ------ | ---- | ------- |
| `PROTOCOL_VERSION_REST/WS/P2P` | `handshake.py:66` | `api/1`, `ws/1`, `p2p/1` |
| `Capability` (StrEnum) | `handshake.py:65` | feature tokens; `ALL_CAPABILITIES` `:89`; includes `delta`, `vector_clocks`, and additive p2p `peer_download` (ADR-0028) |
| `encode_capabilities` / `decode_capabilities` | `handshake.py:96` / `:101` | tokens ⇄ enum set |
| `WsAuthRequest` / `WsAuthResponse` TypedDicts | `handshake.py:114` / `:124` | WS auth frames |
| `build_ws_auth_request` | `handshake.py:136` | client/android → server (protocol_version, app_version, capabilities, token) |
| `build_ws_auth_ok` / `build_ws_auth_error` | `handshake.py:149` / `:162` | server → client (ok lists server caps; error carries client_protocol_version) |
| `P2PAuthRequiredFrame` / `P2PAuthFrame` / `P2PAuthResultFrame` / `P2PHelloFrame` | `handshake.py:196`–`240` | p2p master⇄slave handshake TypedDicts (ADR-0024) |
| `build_p2p_auth_required` / `build_p2p_auth` / `build_p2p_auth_ok` / `build_p2p_auth_failed` / `build_p2p_hello` | `handshake.py:243`–`296` | p2p-WSS frame builders: greeting, auth frame (+token/cid), ok/failed replies, hello (both directions) |

Strict policy: a protocol-version mismatch is a **hard fail** (server replies
error / 426; peers disconnect / auth refused). Capabilities are feature flags
within a version — intersection semantics, never cross-version negotiation
(ADR-0024).

## bootnode.py — `boot/1` bootstrap mirror (ADR-0032, ADR-0033)

Mirror of the canonical `boot/1` contract (`hsync-bootnode/protocol-spec/boot-1.md`
+ `hsync-bootnode/fixtures/`). The daemon keeps its own frame models and does not
import this mirror; its Python v1 reuses only generic `hsync-common` utilities
(`ssl_utils`, `CID_PATTERN`, `is_valid_bucket_name` — ADR-0033).

- `PROTOCOL_VERSION_BOOT = "boot/1"` (`bootnode.py:69`), `BOOT_ALPN = "hsync-boot/1"`.
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
  `is_valid_bucket_token`, `constant_time_equals`, `verify_bucket_token`.
- Fixture mirror `protocol/fixtures/bootnode-*.json` is byte-checked against the
  canonical bootnode fixtures by `tests/test_protocol_bootnode.py`.
- Consumers: `hsync-client` (bootnode discovery), shared fixtures/tests.

## capabilities.py — `--capabilities-json` document

- `CAPABILITIES_SCHEMA_VERSION = 3` (`capabilities.py:56`); the desktop rejects
  any other version outright.
- `ProtocolVersions` (`capabilities.py:59`) carries `rest`, `ws`, `p2p`, `boot`;
  `CapabilitiesDoc` (`:68`) is the document TypedDict.
- `build_capabilities` (`:80`) aggregates the supported subcommands, the
  per-subcommand CLI option flags, the protocol versions and the events schema
  version.
- `parse_capabilities` (`:124`) rejects unknown schema versions, missing keys
  **and** wrong field types (`_field_types_valid` `:151`; the document crosses a
  process boundary, so a malformed `subcommands`/`cli_options`/`capabilities`
  must be refused, not mis-parsed).
- `supports_cli_option` (`:187`, scoped to one subcommand or on the union of
  all) and `supports_subcommand` (`:207`) back the desktop gating. Emitted by
  the client `--capabilities-json` global flag, consumed by desktop to
  enable/disable controls.

## events.py — UI/telemetry event stream

- `EVENTS_SCHEMA_VERSION = 2` (`events.py:41`).
- `UiEventName` StrEnum (`events.py:44`) — the structured events emitted by the
  client and consumed by desktop/android (incl. `sync_paused`,
  `transfer_failed`, `fingerprint_changed`, `auth_required`, `pairing_needed`,
  `duplicate_identity`, `security_rejected`, `discovery`).
- `discovery` carries `plan` (`mdns` | `bootnode`) and, with the bootnode plan,
  the `bootnode` host: the client emits it once at `hsync p2p` startup so a GUI
  can surface the active discovery plan instead of silently degrading to mDNS.
  Adding it is additive (the payload stays a flat optional-field object and
  `parse_event_line` ignores unknown names), so `EVENTS_SCHEMA_VERSION` stays 2.
- `UiEventDict` (`events.py:85`) includes optional `source_cid` only for a
  successful verified peer-served full download; build/serialize/parse:
  `build_event` (`:119`), `serialize_event` (`:141`), `parse_event_line` (`:146`).

## p2p.py — p2p wire SSOT (master election + p2p-only paths)

- Realtime control-plane path: `P2P_WS_EVENTS_PATH` (`p2p.py:64`) template and
  `p2p_ws_events_path(bucket, cid)` (`p2p.py:67`); the master registers the
  template, the client builds the concrete path, and the Android mirror
  (`PeerDownloadContracts.kt`) matches it. The bucket prefix comes from
  `protocol.rest`.
- p2p-only endpoint `P2P_FILES_SOURCES_SUFFIX` (`p2p.py:58`): source resolution
  has no hsync-server counterpart; its concrete path is built with
  `rest_bucket_path`.
- `ElectionCandidate` dataclass (`p2p.py:77`).
- Ordering key `election_sort_key` (`p2p.py:92`); SSOT ranking
  `rank_election_candidates` (`p2p.py:107`) returns the full ranked list
  (never_master filtered out); `elect_master` (`p2p.py:121`) is its
  winner-only projection; `SYNC_DIRECTION_BIDIRECTIONAL` (`p2p.py:54`).
- The client `hsync_client/p2p.py` consumes `rank_election_candidates` for
  master, successor and the force_master conflict subset; android
  `Election.kt` mirrors the ordering; parity is pinned by the
  `p2p-election-scenarios` fixture.

## rest.py — REST surface SSOT (paths shared with hsync-server)

- `REST_API_PREFIX` (`rest.py:61`), service paths (`REST_HEALTH_PATH` `:64`,
  `REST_METRICS_PATH`, `REST_TIME_PATH`) and the admin surface.
- `REST_BUCKETS_PREFIX` (`rest.py:78`) plus the `REST_*_SUFFIX` constants
  (`:79-94`), with `rest_bucket_base` (`:96`), `rest_bucket_path` (`:101`),
  `rest_bucket_template` (`:106`) and `rest_delta_data_path` (`:111`).
- `REST_PATH_TEMPLATES` (`rest.py:119`) is the whole named surface, compared
  **byte-for-byte** with the committed OpenAPI snapshot (`__init__.py:30`) by
  `tests/test_protocol_rest.py`; a server route change fails that test until
  this module is updated, so clients cannot drift.
- Consumers: `hsync-client` (server API requests, peer-download mirror) and the
  Android mirror (`PeerDownloadContracts.kt`).

## pairing.py — TOFU pin + p2p-key policy

- `PinDecision` StrEnum (`pairing.py:66`); `normalize_fingerprint`
  (`pairing.py:89`); `evaluate_pin` (`pairing.py:124`).
- Bootnode trust primitives (ADR-0034): `parse_fingerprint` (`pairing.py:102`)
  normalizes `sha256:<hex>` / bare hex to lowercase 64-char hex (rejects invalid),
  `fingerprint_matches` (`pairing.py:153`) compares constant-time against a pin
  set, `FingerprintMismatch` (`pairing.py:80`) is the shared fatal-exception.
  Consumers: `hsync-client` bootnode pinning; future Rust/Android parity.
- `requires_pairing_confirmation` (`pairing.py:174`) — strict out-of-band pairing.
- `is_write_direction` (`pairing.py:194`) + `p2p_write_requires_key`
  (`pairing.py:199`); write directions set `pairing.py:63`. ADR-0029 makes every
  write-capable run require a key unless the explicit dangerous
  `allow_unauthenticated_writes` opt-in is set.

## peer_download.py — strict p2p peer-download wire contract

- Payload TypedDicts cover batch source request/response candidates,
  snapshot/delta inventory entries and frames, and cumulative ACKs
  (`peer_download.py:91`–`:164`).
- `validate_p2p_sources_request` / `validate_p2p_sources_response` and matching
  builders enforce exact keys, canonical normalized paths, lowercase hashes,
  CID/candidate uniqueness, IP-literal HTTPS endpoints, 500-file/8-candidate
  limits, and the 2 MiB compact-payload ceiling (`peer_download.py:289`–`:468`).
- `validate_p2p_inventory_frame` / `validate_p2p_inventory_ack` and matching
  builders enforce mode-specific entries, non-boolean signed-64-bit counters,
  duplicate-path rejection, terminal empty snapshots, strict ACK reasons, and
  the shared 2 MiB/500-entry bounds (`peer_download.py:374`–`:507`).

## schemas.py — JSON-Schema builders (draft 2020-12)

- Dialect const `schemas.py:59`; p2p TXT key sets `:63`/`:71`/`:85` include the
  optional `peer_download` implementation flag. Live seeder capacity is not a TXT
  fact: it travels on the authenticated handshake (ADR-0030).
- `build_ws_schema` (`schemas.py:464`), `build_p2p_wss_schema` (`:669`; pins
  auth/hello plus additive inventory/ACK frames, ADR-0024/0028),
  `build_p2p_sources_schema` (`:180`), and `build_p2p_txt_schema` (`:742`) derive
  enums/objects and bounds from `handshake`, `peer_download`, `events`, and the
  `models/` types. Shared capabilities-array schema is `_capabilities_array`.

## fixtures.py — cross-language golden fixtures

- `build_fixtures` (`fixtures.py`) assembles file-event, master/seeder p2p TXT,
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

- Artifact path constants: `REST_OPENAPI_PATH` (`__init__.py:30`),
  `WS_SCHEMA_PATH` (`:34`), `P2P_TXT_SCHEMA_PATH` (`:35`),
  `P2P_WSS_SCHEMA_PATH` (`:36`), `P2P_SOURCES_SCHEMA_PATH` (`:38`),
  `FIXTURES_DIR` (`:42`), `ANDROID_FIXTURES_DIR` (`:48`).
- Canonical dump/load: `dump_contract`/`load_contract` (`__init__.py:60`/`:69`),
  with `dump_openapi` (`:74`) reusing them.

## Change checklist

Editing any of the above ⇒ rerun `scripts/export_protocol_schemas.py`
(+ `export_openapi.py` for REST), regenerate fixtures, and confirm
`tests/test_protocol_schemas.py` / `test_capabilities.py` stay green. Update the
Kotlin mirrors (`Protocol.kt`, `Election.kt`, `Pairing.kt`) in the same change.

> Decision rationale (versioning, election, tombstones, conflict model):
> [../decisions.md](../decisions.md) → `../../docs/adr/`.
