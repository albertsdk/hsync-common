# HSYNC Common Library — `protocol/` package

Versioned wire contract + generators. This is the SSOT; never redefine these
constants in consumers.

## handshake.py — versions, capabilities, WS + LAN-WSS auth

| Symbol | Line | Purpose |
| ------ | ---- | ------- |
| `PROTOCOL_VERSION_REST/WS/LAN` | `handshake.py:60` | `api/1`, `ws/1`, `lan/1` |
| `Capability` (StrEnum) | `handshake.py:65` | feature tokens; `ALL_CAPABILITIES` `:89`; includes `delta`, `vector_clocks`, and additive LAN `peer_download` (ADR-0028) |
| `encode_capabilities` / `decode_capabilities` | `handshake.py:96` / `:101` | tokens ⇄ enum set |
| `WsAuthRequest` / `WsAuthResponse` TypedDicts | `handshake.py:114` / `:124` | WS auth frames |
| `build_ws_auth_request` | `handshake.py:136` | client/android → server (protocol_version, app_version, capabilities, token) |
| `build_ws_auth_ok` / `build_ws_auth_error` | `handshake.py:149` / `:162` | server → client (ok lists server caps; error carries client_protocol_version) |
| `LanAuthRequiredFrame` / `LanAuthFrame` / `LanAuthResultFrame` / `LanHelloFrame` | `handshake.py:196`–`240` | LAN master⇄slave handshake TypedDicts (ADR-0024) |
| `build_lan_auth_required` / `build_lan_auth` / `build_lan_auth_ok` / `build_lan_auth_failed` / `build_lan_hello` | `handshake.py:243`–`296` | LAN-WSS frame builders: greeting, auth frame (+token/cid), ok/failed replies, hello (both directions) |

Strict policy: a protocol-version mismatch is a **hard fail** (server replies
error / 426; peers disconnect / auth refused). Capabilities are feature flags
within a version — intersection semantics, never cross-version negotiation
(ADR-0024).

## events.py — UI/telemetry event stream

- `EVENTS_SCHEMA_VERSION = 2` (`events.py:41`).
- `UiEventName` StrEnum (`events.py:44`) — the structured events emitted by the
  client and consumed by desktop/android (incl. `sync_paused`,
  `transfer_failed`, `fingerprint_changed`, `auth_required`, `pairing_needed`,
  `duplicate_identity`, `security_rejected`).
- `UiEventDict` (`events.py:85`) includes optional `source_cid` only for a
  successful verified peer-served full download; build/serialize/parse:
  `build_event` (`:119`), `serialize_event` (`:141`), `parse_event_line` (`:146`).

## lan.py — master election SSOT

- `ElectionCandidate` dataclass (`lan.py:52`).
- Ordering key `election_sort_key` (`lan.py:67`); SSOT ranking
  `rank_election_candidates` (`lan.py:83`) returns the full ranked list
  (never_master filtered out); `elect_master` (`lan.py:97`) is its
  winner-only projection; `SYNC_DIRECTION_BIDIRECTIONAL` (`lan.py:48`).
- The client `hsync_client/lan.py` consumes `rank_election_candidates` for
  master, successor and the force_master conflict subset; android
  `Election.kt` mirrors the ordering; parity is pinned by the
  `lan-election-scenarios` fixture.

## pairing.py — TOFU pin + LAN-key policy

- `PinDecision` StrEnum (`pairing.py:59`); `normalize_fingerprint`
  (`pairing.py:73`); `evaluate_pin` (`pairing.py:86`).
- `requires_pairing_confirmation` (`pairing.py:115`) — strict out-of-band pairing.
- `is_write_direction` (`pairing.py:135`) + `lan_write_requires_key`
  (`pairing.py:140`); write directions set `pairing.py:56`. ADR-0029 makes
  interactive and unattended writes equivalent: a key is required unless the
  explicit dangerous `allow_unauthenticated_writes` opt-in is set.

## peer_download.py — strict LAN peer-download wire contract

- Payload TypedDicts cover batch source request/response candidates,
  snapshot/delta inventory entries and frames, and cumulative ACKs
  (`peer_download.py:91`–`:164`).
- `validate_lan_sources_request` / `validate_lan_sources_response` and matching
  builders enforce exact keys, canonical normalized paths, lowercase hashes,
  CID/candidate uniqueness, IP-literal HTTPS endpoints, 500-file/8-candidate
  limits, and the 2 MiB compact-payload ceiling (`peer_download.py:289`–`:468`).
- `validate_lan_inventory_frame` / `validate_lan_inventory_ack` and matching
  builders enforce mode-specific entries, non-boolean signed-64-bit counters,
  duplicate-path rejection, terminal empty snapshots, strict ACK reasons, and
  the shared 2 MiB/500-entry bounds (`peer_download.py:374`–`:507`).

## capabilities.py — capabilities document (desktop UI gating)

- `CAPABILITIES_SCHEMA_VERSION = 2` (`capabilities.py:54`); `CapabilitiesDoc`
  TypedDict (`:65`).
- `build_capabilities` (`capabilities.py:77`) aggregates the supported
  subcommands, the per-subcommand CLI option flags, protocol versions and
  events schema version; `parse_capabilities` (`:120`) rejects unknown schema
  versions, missing keys **and** wrong field types (the document crosses a
  process boundary, so a malformed `subcommands`/`cli_options`/`capabilities`
  must be refused, not mis-parsed); `supports_cli_option` (`:185`, scoped to
  one subcommand or on the union of all) and `supports_subcommand` (`:205`).
  Emitted by the client `--capabilities-json` global flag, consumed by desktop
  to enable/disable controls.

## schemas.py — JSON-Schema builders (draft 2020-12)

- Dialect const `schemas.py:59`; LAN TXT key sets `:63`/`:71`/`:85` include the
  optional `peer_download` implementation flag and bound-seeder `seed` state.
- `build_ws_schema` (`schemas.py:464`), `build_lan_wss_schema` (`:669`; pins
  auth/hello plus additive inventory/ACK frames, ADR-0024/0028),
  `build_lan_sources_schema` (`:180`), and `build_lan_txt_schema` (`:742`) derive
  enums/objects and bounds from `handshake`, `peer_download`, `events`, and the
  `models/` types. Shared capabilities-array schema is `_capabilities_array`.

## fixtures.py — cross-language golden fixtures

- `build_fixtures` (`fixtures.py`) assembles file-event, master/seeder LAN TXT,
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
  `WS_SCHEMA_PATH` (`:34`), `LAN_TXT_SCHEMA_PATH` (`:35`),
  `LAN_WSS_SCHEMA_PATH` (`:36`), `LAN_SOURCES_SCHEMA_PATH` (`:38`),
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
