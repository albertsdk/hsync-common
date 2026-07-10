# HSYNC Common Library — `protocol/` package

Versioned wire contract + generators. This is the SSOT; never redefine these
constants in consumers.

## handshake.py — versions, capabilities, WS auth

| Symbol | Line | Purpose |
| ------ | ---- | ------- |
| `PROTOCOL_VERSION_REST/WS/LAN` | `handshake.py:44` | `api/1`, `ws/1`, `lan/1` |
| `Capability` (StrEnum) | `handshake.py:49` | feature tokens; `ALL_CAPABILITIES` `:62`; includes `delta` for rsync-style block sync |
| `encode_capabilities` / `decode_capabilities` | `handshake.py:65` / `:70` | tokens ⇄ enum set |
| `WsAuthRequest` / `WsAuthResponse` TypedDicts | `handshake.py:82` / `:92` | WS auth frames |
| `build_ws_auth_request` | `handshake.py:104` | client/android → server (protocol_version, app_version, capabilities, token) |
| `build_ws_auth_ok` / `build_ws_auth_error` | `handshake.py:117` / `:130` | server → client (ok lists server caps; error carries client_protocol_version) |

Strict policy: a protocol-version mismatch is a **hard fail** (server replies
error / 426; peers disconnect). No semver negotiation.

## events.py — UI/telemetry event stream

- `EVENTS_SCHEMA_VERSION = 1` (`events.py:40`).
- `UiEventName` StrEnum (`events.py:43`) — the structured events emitted by the
  client and consumed by desktop/android (incl. `sync_paused`,
  `transfer_failed`, `fingerprint_changed`, `auth_required`, `pairing_needed`,
  `security_rejected`).
- `UiEventDict` (`events.py:77`); build/serialize/parse: `build_event`
  (`:113`), `serialize_event` (`:135`), `parse_event_line` (`:140`).

## lan.py — master election SSOT

- `ElectionCandidate` dataclass (`lan.py:52`).
- Ordering key `election_sort_key` (`lan.py:67`) and `elect_master`
  (`lan.py:82`); `SYNC_DIRECTION_BIDIRECTIONAL` (`lan.py:48`).
- Mirrored by client `hsync_client/lan.py` and android `Election.kt`; parity is
  pinned by the `lan-election-scenarios` fixture.

## pairing.py — TOFU pin + LAN-key policy

- `PinDecision` StrEnum (`pairing.py:58`); `normalize_fingerprint`
  (`pairing.py:72`); `evaluate_pin` (`pairing.py:85`).
- `requires_pairing_confirmation` (`pairing.py:114`) — strict out-of-band pairing.
- `is_write_direction` (`pairing.py:134`) + `lan_write_requires_key`
  (`pairing.py:139`); write directions set `pairing.py:55`.

## capabilities.py — capabilities document (desktop UI gating)

- `CAPABILITIES_SCHEMA_VERSION = 1` (`capabilities.py:52`); `CapabilitiesDoc`
  TypedDict (`:63`).
- `build_capabilities` (`capabilities.py:74`) aggregates protocol versions,
  events schema version and CLI options; `parse_capabilities` (`:107`);
  `supports_cli_option` (`:132`). Emitted by the client `--capabilities-json`
  flag, consumed by desktop to enable/disable controls.

## schemas.py — JSON-Schema builders (draft 2020-12)

- Dialect const `schemas.py:45`; LAN TXT key sets `:49`/`:57`/`:66` (includes `delta` optional key for rsync-style block sync capability).
- `build_ws_schema` (`schemas.py:223`) and `build_lan_txt_schema`
  (`schemas.py:269`) derive enums/objects from `handshake`, `events` and the
  `models/` types (object builders `_file_object` `:82` … `_event_message` `:135`).

## fixtures.py — cross-language golden fixtures

- `build_fixtures` (`fixtures.py:241`) assembles file-event, LAN TXT, election,
  pin/write-policy and pairing scenarios from the SSOT builders.
- Consumed by Python drift tests and copied into Android test resources for
  parity (`test_protocol_schemas.py`, android `ProtocolContractTest`).

## __init__.py — paths & (de)serialization

- Artifact path constants: `REST_OPENAPI_PATH` (`__init__.py:30`),
  `WS_SCHEMA_PATH` (`:34`), `LAN_TXT_SCHEMA_PATH` (`:35`), `FIXTURES_DIR`
  (`:39`), `ANDROID_FIXTURES_DIR` (`:45`).
- Canonical dump/load: `dump_contract`/`load_contract` (`__init__.py:57`/`:66`),
  with `dump_openapi`/`load_openapi` (`:71`/`:76`) reusing them.

## Change checklist

Editing any of the above ⇒ rerun `scripts/export_protocol_schemas.py`
(+ `export_openapi.py` for REST), regenerate fixtures, and confirm
`tests/test_protocol_schemas.py` / `test_capabilities.py` stay green. Update the
Kotlin mirrors (`Protocol.kt`, `Election.kt`, `Pairing.kt`) in the same change.

> Decision rationale (versioning, election, tombstones, conflict model):
> [../decisions.md](../decisions.md) → `../../docs/adr/`.
