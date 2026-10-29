# HSYNC Common Library — Architecture (agent view)

Shared, dependency-light library. No process of its own; it is imported by the
runtime projects and re-implemented (by mirroring) in Kotlin for Android.

## Layering

```
constants / format / text / env / clock        (leaf utilities, no internal deps)
        │
hashing / compression / permissions / path_validation / ignore / ssl_utils / logger / labels
        │
models/  (File, Dir, Symlink, Event, SyncAction, Tombstone, Version)
        │
protocol/  (versions, capabilities, handshake, events, p2p, pairing, peer_download,
            rendezvous, rest, tls_trust, schemas, fixtures)
```

Higher layers may import lower ones; the reverse never happens. `protocol/`
derives its JSON Schemas and fixtures from `models/` + `handshake`, so the wire
contract is mechanically tied to the in-code types.

## Package layout

| Path | Responsibility | Wiki |
| ---- | -------------- | ---- |
| `hsync_common/constants.py::HSYNC_VERSION` | `HSYNC_VERSION`, wire/checksum header names + client-name validator, content types, sentinel filenames, chunk-size tiers, `.part` suffix | [utilities](modules/utilities.md) |
| `hsync_common/models/` | Canonical sync data types; `folder.py` (`.hsyncfolder` + state-dir helpers), `sqlstore.py` (per-folder state DB) | [data-models](data-models.md) |
| `hsync_common/protocol/` | Versioned wire protocol + contract artifacts | [protocol](modules/protocol.md) |
| `hsync_common/{hashing,compression,permissions,path_validation,ignore,ssl_utils,logger,labels,env,text,clock,format,time_utils,endpoint,runtime,ratelimit,upnp,exceptions}.py`, `hsync_common/delta/` | Cross-cutting helpers | [utilities](modules/utilities.md) |

## Protocol SSOT → consumers

The protocol package is the authoritative contract; consumers must not redefine
these constants:

| SSOT symbol | Location | Consumed by |
| ----------- | -------- | ----------- |
| `PROTOCOL_VERSION_REST/WS/P2P` | `protocol/handshake.py::PROTOCOL_VERSION_REST` | server middleware, client REST/WS, android `Protocol.kt` |
| `Capability` enum + `encode/decode_capabilities` | `protocol/handshake.py::Capability` | WS handshake on all peers; includes `index` (read-only inventory) and `peer_download` (block serving) |
| `build_ws_auth_request/ok/error` + presence frame | `protocol/handshake.py::build_ws_auth_request` | client/android WS auth, server `events.py` |
| `UiEventName` + `build_event` | `protocol/events.py::UiEventName` | client emits, desktop/android parse; transfer payload may carry peer `source_cid` |
| `elect_master` / `election_sort_key` | `protocol/p2p.py::elect_master` | client `p2p_peers.py`, android `Election.kt` |
| `evaluate_pin` / `p2p_write_requires_key` | `protocol/pairing.py::evaluate_pin` | client `pinning.py`, android `Pairing.kt` |
| p2p source/inventory builders + validators | `protocol/peer_download.py::validate_p2p_sources_request` | client master/seeder/source resolver, Android mirror, generated contracts |

## Causal conflict model (ADR-0022)

- `models/version.py` is the SSOT for per-file causal versions: `FileVersion`
  (private, persisted), `VersionInfo` (wire form), `compare/tick/merge_vclocks`,
  `resolve_three_way` (the §3.2 decision matrix); the SQLite-backed
  `SyncStateStore` lives in `models/version_store.py` (re-exported from
  `models/version.py`; per-folder SQLite DB keyed by ``.hsyncfolder``
  UUID, ADR-0025).
  No node is authoritative: the server and the
  elected p2p master arbitrate uploads causally against their stored version
  and never decide by role.
- Wire surface: `FileDict.version` (attach-always), upload form fields
  `vclock`/`version_id`, delta-apply metadata, WS auth/TXT capability token
  `vector_clocks` (same protocol versions: `api/1`, `ws/1`, `p2p/1`).
- Consumers: client `sync.py`/`sync_state.py`/`arbitration.py`, server
  `versions.py`/`arbitration.py`, Android `Version.kt`/`Arbitration.kt`
  mirrors. `protocol/fixtures.py` generates `causal-resolution-scenarios.json`
  to pin Python and Kotlin to the same decision matrix.
- See [ADR-0022](../docs/internal/adr/0022-causal-vector-clock-conflict-model.md)
  and [decisions.md](decisions.md).

## Contract artifacts (generated, committed, drift-tested)

| Artifact | Builder | Path constant |
| -------- | ------- | ------------- |
| OpenAPI (REST) | server app → `dump_openapi` | `protocol/__init__.py::REST_OPENAPI_PATH` |
| WS JSON Schema | `build_ws_schema` (`protocol/schemas.py::build_ws_schema`) | `protocol/__init__.py::WS_SCHEMA_PATH` |
| p2p TXT JSON Schema | `build_p2p_txt_schema` (`protocol/schemas.py::build_p2p_txt_schema`) | `protocol/__init__.py::P2P_TXT_SCHEMA_PATH` |
| p2p WSS JSON Schema | `build_p2p_wss_schema` (`protocol/schemas.py::build_p2p_wss_schema`) | `protocol/__init__.py::P2P_WSS_SCHEMA_PATH` |
| p2p source JSON Schema | `build_p2p_sources_schema` (`protocol/schemas.py::build_p2p_sources_schema`) | `protocol/__init__.py::P2P_SOURCES_SCHEMA_PATH` |
| Cross-language fixtures | `build_fixtures` (`protocol/fixtures.py::build_fixtures`) | `protocol/__init__.py::FIXTURES_DIR` |

Regeneration: `scripts/export_protocol_schemas.py` here and
`hsync-server/scripts/export_openapi.py` (it imports the server app).
Drift is enforced by `tests/test_protocol_schemas.py` (rebuild must equal the
committed snapshot). `ANDROID_FIXTURES_DIR` (`protocol/__init__.py::ANDROID_FIXTURES_DIR`)
lets the common suite optionally assert byte-equality with the Android resources;
`RENDEZVOUS_FIXTURES_DIR` (`protocol/__init__.py::RENDEZVOUS_FIXTURES_DIR`) points at
the canonical `hsync-rendezvous` fixtures mirrored under `protocol/fixtures/`.

## Consumer contract

- Path dependency with `develop = true`: edits to `hsync_common` are picked up
  live by client/server/desktop without reinstall.
- Per *Zero Backward Compatibility* (`AGENTS.md`), there are **no compatibility
  shims**: consumers import directly from `hsync_common.*`.
- Android does not import Python; it mirrors the SSOT in Kotlin and the shared
  fixtures pin both languages to identical behavior.

> Human-oriented overview, model attribute tables and rationale: `../docs/internal/architecture.md`.
> Decision rationale: [decisions.md](decisions.md) → `../docs/internal/adr/`.
