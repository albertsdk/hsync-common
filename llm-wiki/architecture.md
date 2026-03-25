# HSYNC Common Library — Architecture (agent view)

Shared, dependency-light library. No process of its own; it is imported by the
runtime projects and re-implemented (by mirroring) in Kotlin for Android.

## Layering

```
constants / format / text / env / clock        (leaf utilities, no internal deps)
        │
hashing / compression / permissions / path_validation / ignore / ssl_utils / logger
        │
models/  (File, Dir, Symlink, Event, SyncAction, Tombstone, Version)
        │
protocol/  (versions, capabilities, handshake, events, lan, pairing, schemas, fixtures)
```

Higher layers may import lower ones; the reverse never happens. `protocol/`
derives its JSON Schemas and fixtures from `models/` + `handshake`, so the wire
contract is mechanically tied to the in-code types.

## Package layout

| Path | Responsibility | Wiki |
| ---- | -------------- | ---- |
| `hsync_common/constants.py:24` | `HSYNC_VERSION`, wire/checksum header names + client-name validator, content types, sentinel filenames, chunk-size tiers, `.part` suffix | [utilities](modules/utilities.md) |
| `hsync_common/models/` | Canonical sync data types; `folder.py` (`.hsyncfolder` + state dir), `sqlstore.py` (`syncstate.db`) | [data-models](data-models.md) |
| `hsync_common/protocol/` | Versioned wire protocol + contract artifacts | [protocol](modules/protocol.md) |
| `hsync_common/{hashing,compression,permissions,path_validation,ignore,ssl_utils,logger,env,text,clock,format,exceptions}.py` | Cross-cutting helpers | [utilities](modules/utilities.md) |

## Protocol SSOT → consumers

The protocol package is the authoritative contract; consumers must not redefine
these constants:

| SSOT symbol | Location | Consumed by |
| ----------- | -------- | ----------- |
| `PROTOCOL_VERSION_REST/WS/LAN` | `protocol/handshake.py:60` | server middleware, client REST/WS, android `Protocol.kt` |
| `Capability` enum + `encode/decode_capabilities` | `protocol/handshake.py:65` | WS handshake on all peers; includes additive `peer_download` |
| `build_ws_auth_request/ok/error` | `protocol/handshake.py:136` | client/android WS auth, server `events.py` |
| `UiEventName` + `build_event` | `protocol/events.py:44` | client emits, desktop/android parse; transfer payload may carry peer `source_cid` |
| `elect_master` / `election_sort_key` | `protocol/lan.py:67` | client `lan.py`, android `Election.kt` |
| `evaluate_pin` / `lan_write_requires_key` | `protocol/pairing.py:86` | client `pinning.py`, android `Pairing.kt` |
| LAN source/inventory builders + validators | `protocol/peer_download.py:91` | client master/seeder/source resolver, Android mirror, generated contracts |

## Causal conflict model (ADR-0022)

- `models/version.py` is the SSOT for per-file causal versions: `FileVersion`
  (private, persisted), `VersionInfo` (wire form), `compare/tick/merge_vclocks`,
  `resolve_three_way` (the §3.2 decision matrix); the SQLite-backed
  `SyncStateStore` lives in `models/version_store.py` (re-exported from
  `models/version.py`; installation ``syncstate.db`` keyed by ``.hsyncfolder``
  UUID, ADR-0025).
  No node is authoritative: the server and the
  elected LAN master arbitrate uploads causally against their stored version
  and never decide by role.
- Wire surface: `FileDict.version` (attach-always), upload form fields
  `vclock`/`version_id`, delta-apply metadata, WS auth/TXT capability token
  `vector_clocks` (same protocol versions: `api/1`, `ws/1`, `lan/1`).
- Consumers: client `sync.py`/`sync_state.py`/`arbitration.py`, server
  `versions.py`/`arbitration.py`, Android `Version.kt`/`Arbitration.kt`
  mirrors. `protocol/fixtures.py` generates `causal-resolution-scenarios.json`
  to pin Python and Kotlin to the same decision matrix.
- See [ADR-0022](../docs/internal/adr/0022-causal-vector-clock-conflict-model.md)
  and [decisions.md](decisions.md).

## Contract artifacts (generated, committed, drift-tested)

| Artifact | Builder | Path constant |
| -------- | ------- | ------------- |
| OpenAPI (REST) | server app → `dump_openapi` | `protocol/__init__.py:30` (`REST_OPENAPI_PATH`) |
| WS JSON Schema | `build_ws_schema` (`protocol/schemas.py:464`) | `protocol/__init__.py:34` (`WS_SCHEMA_PATH`) |
| LAN TXT JSON Schema | `build_lan_txt_schema` (`protocol/schemas.py:742`) | `protocol/__init__.py:35` (`LAN_TXT_SCHEMA_PATH`) |
| LAN WSS JSON Schema | `build_lan_wss_schema` (`protocol/schemas.py:669`) | `protocol/__init__.py:36` (`LAN_WSS_SCHEMA_PATH`) |
| LAN source JSON Schema | `build_lan_sources_schema` (`protocol/schemas.py:180`) | `protocol/__init__.py:38` (`LAN_SOURCES_SCHEMA_PATH`) |
| Cross-language fixtures | `build_fixtures` (`protocol/fixtures.py:647`) | `protocol/__init__.py:42` (`FIXTURES_DIR`) |

Regeneration: `scripts/export_protocol_schemas.py` and `scripts/export_openapi.py`.
Drift is enforced by `tests/test_protocol_schemas.py` (rebuild must equal the
committed snapshot). `ANDROID_FIXTURES_DIR` (`protocol/__init__.py:45`) lets the
common suite optionally assert byte-equality with the Android resources.

## Consumer contract

- Path dependency with `develop = true`: edits to `hsync_common` are picked up
  live by client/server/desktop without reinstall.
- Per *Zero Backward Compatibility* (`CLAUDE.md`), there are **no compatibility
  shims**: consumers import directly from `hsync_common.*`.
- Android does not import Python; it mirrors the SSOT in Kotlin and the shared
  fixtures pin both languages to identical behavior.

> Human-oriented overview, model attribute tables and rationale: `../docs/architecture.md`.
> Decision rationale: [decisions.md](decisions.md) → `../docs/adr/`.
