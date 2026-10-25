# HSYNC Common Library — LLM Wiki (Index)

Agent-optimized knowledge base for `hsync-common`, the shared library that is the
single source of truth for data models, the wire protocol, and cross-cutting
utilities consumed by every other HSYNC project (client, server, desktop,
android).

> End-user / human docs live in [`../docs/`](../docs/internal/architecture.md). This wiki
> is the **first search surface**: start here, follow the `path::symbol`
> references to reach code directly.

## Map

| Doc | Scope |
| --- | ----- |
| [architecture.md](architecture.md) | Package layout, layering, consumer contract, how the protocol SSOT flows outward |
| [data-models.md](data-models.md) | Dataclasses/TypedDicts in `models/` (File, Dir, Symlink, Event, SyncAction, Tombstone, Version) + serialization shapes |
| [modules/protocol.md](modules/protocol.md) | `protocol/` package: versions, capabilities, handshake, events, p2p election, pairing, JSON-Schema builders, fixtures |
| [modules/utilities.md](modules/utilities.md) | Cross-cutting helpers: hashing, compression, ignore, path validation, permissions, ssl, logger, labels, env, text, clock, format, endpoint, disk free-space guards, bucket listing, upload arbitration, `.hsynckeep` sentinels, delta download tokens, CLI/GUI shared defaults |
| [modules/benchmarks.md](modules/benchmarks.md) | L1 micro-benchmark suite (`bench/`): tiers, scenario→code anchors, methodology, findings |
| [decisions.md](decisions.md) | Pointer to the committed ADRs under `../docs/internal/adr/` (ecosystem-wide decisions) |

## Quick facts

- Package root: `hsync_common/` (package: `hsync_common/__init__.py`).
- Version SSOT: `HSYNC_VERSION = "1.0.7"` (`hsync_common/constants.py::HSYNC_VERSION`).
- REST header names SSOT: `HEADER_CLIENT_NAME/CLIENT_VERSION/SERVER_VERSION/PROTOCOL_VERSION`
  plus full-download `HEADER_CHECKSUM_SHA256` (`hsync_common/constants.py::HEADER_CLIENT_NAME`);
  slug validator `is_valid_client_name` (`hsync_common/constants.py::is_valid_client_name`) is shared with the server middleware.
- Wire content types SSOT: `CONTENT_TYPE_OCTET_STREAM` / `CONTENT_TYPE_JSON`
  (`hsync_common/constants.py::CONTENT_TYPE_OCTET_STREAM`) shared by client, server and Android.
- Protocol versions SSOT: `hsync_common/protocol/handshake.py::PROTOCOL_VERSION_REST`
  (REST `api/1`, WS `ws/1`, p2p `p2p/1`); bootstrap `boot/1` mirrors `hsync-bootnode` in
  `hsync_common/protocol/bootnode.py::PROTOCOL_VERSION_BOOT`.
- Consumed as a Poetry path dependency (`hsync-common = {path = "../hsync-common", develop = true}`) by client, server, desktop; mirrored in Kotlin by android.
- Contract artifacts (committed snapshots, generated from Python SSOT and drift-tested): `protocol/rest/openapi.json`, `protocol/ws/ws-schema.json`, `protocol/p2p/txt-schema.json`, `protocol/p2p/wss-schema.json`, `protocol/p2p/sources-schema.json`, `protocol/fixtures/`.

## Conventions used in this wiki

- Every claim is anchored to code via `path::symbol` (never line numbers).
- No large code blocks are duplicated; intent is described and the code is referenced.
- Kept in sync with `../docs/` per the Dual-Docs rule in `AGENTS.md`.
