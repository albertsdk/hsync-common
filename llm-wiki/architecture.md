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
| `hsync_common/constants.py:20` | `VERSION`, sentinel filenames, chunk-size tiers, `.part` suffix | [utilities](modules/utilities.md) |
| `hsync_common/models/` | Canonical sync data types | [data-models](data-models.md) |
| `hsync_common/protocol/` | Versioned wire protocol + contract artifacts | [protocol](modules/protocol.md) |
| `hsync_common/{hashing,compression,permissions,path_validation,ignore,ssl_utils,logger,env,text,clock,format,exceptions}.py` | Cross-cutting helpers | [utilities](modules/utilities.md) |

## Protocol SSOT → consumers

The protocol package is the authoritative contract; consumers must not redefine
these constants:

| SSOT symbol | Location | Consumed by |
| ----------- | -------- | ----------- |
| `PROTOCOL_VERSION_REST/WS/LAN` | `protocol/handshake.py:44` | server middleware, client REST/WS, android `Protocol.kt` |
| `Capability` enum + `encode/decode_capabilities` | `protocol/handshake.py:49` | WS handshake on all peers |
| `build_ws_auth_request/ok/error` | `protocol/handshake.py:104` | client/android WS auth, server `events.py` |
| `UiEventName` + `build_event` | `protocol/events.py:43` | client emits, desktop/android parse |
| `elect_master` / `election_sort_key` | `protocol/lan.py:67` | client `lan.py`, android `Election.kt` |
| `evaluate_pin` / `lan_write_requires_key` | `protocol/pairing.py:85` | client `pinning.py`, android `Pairing.kt` |

## Contract artifacts (generated, committed, drift-tested)

| Artifact | Builder | Path constant |
| -------- | ------- | ------------- |
| OpenAPI (REST) | server app → `dump_openapi` | `protocol/__init__.py:30` (`REST_OPENAPI_PATH`) |
| WS JSON Schema | `build_ws_schema` (`protocol/schemas.py:223`) | `protocol/__init__.py:34` (`WS_SCHEMA_PATH`) |
| LAN TXT JSON Schema | `build_lan_txt_schema` (`protocol/schemas.py:269`) | `protocol/__init__.py:35` (`LAN_TXT_SCHEMA_PATH`) |
| Cross-language fixtures | `build_fixtures` (`protocol/fixtures.py:241`) | `protocol/__init__.py:39` (`FIXTURES_DIR`) |

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
