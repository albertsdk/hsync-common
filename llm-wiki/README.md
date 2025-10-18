# HSYNC Common Library — LLM Wiki (Index)

Agent-optimized knowledge base for `hsync-common`, the shared library that is the
single source of truth for data models, the wire protocol, and cross-cutting
utilities consumed by every other HSYNC project (client, server, desktop,
android).

> End-user / human docs live in [`../docs/`](../docs/internal/architecture.md). This wiki
> is the **first search surface**: start here, follow the `path/to/file.py:line`
> references to reach code directly.

## Map

| Doc | Scope |
| --- | ----- |
| [architecture.md](architecture.md) | Package layout, layering, consumer contract, how the protocol SSOT flows outward |
| [data-models.md](data-models.md) | Dataclasses/TypedDicts in `models/` (File, Dir, Symlink, Event, SyncAction, Tombstone, Version) + serialization shapes |
| [modules/protocol.md](modules/protocol.md) | `protocol/` package: versions, capabilities, handshake, events, LAN election, pairing, JSON-Schema builders, fixtures |
| [modules/utilities.md](modules/utilities.md) | Cross-cutting helpers: hashing, compression, ignore, path validation, permissions, ssl, logger, labels, env, text, clock, format |
| [decisions.md](decisions.md) | Pointer to the committed ADRs under `../docs/internal/adr/` (ecosystem-wide decisions) |

## Quick facts

- Package root: `hsync_common/` (`hsync_common/__init__.py:1`).
- Version SSOT: `HSYNC_VERSION = "1.0.0"` (`hsync_common/constants.py:24`).
- REST header names SSOT: `HEADER_CLIENT_NAME/CLIENT_VERSION/SERVER_VERSION/PROTOCOL_VERSION`
  (`hsync_common/constants.py:33`); slug validator `is_valid_client_name`
  (`:48`) shared with the server middleware.
- Wire content types SSOT: `CONTENT_TYPE_OCTET_STREAM` / `CONTENT_TYPE_JSON`
  (`hsync_common/constants.py:63`) shared by client, server and Android.
- Protocol versions SSOT: `hsync_common/protocol/handshake.py:53` (REST `api/1`, WS `ws/1`, LAN `lan/1`).
- Consumed as a Poetry path dependency (`hsync-common = {path = "../hsync-common", develop = true}`) by client, server, desktop; mirrored in Kotlin by android.
- Contract artifacts (committed snapshots, generated from Python SSOT and drift-tested): `protocol/rest/openapi.json`, `protocol/ws/ws-schema.json`, `protocol/lan/txt-schema.json`, `protocol/lan/wss-schema.json`, `protocol/fixtures/`.

## Conventions used in this wiki

- Every claim is anchored to code via `path/to/file.py:line`.
- No large code blocks are duplicated; intent is described and the code is referenced.
- Kept in sync with `../docs/` per the Dual-Docs rule in `CLAUDE.md`.
