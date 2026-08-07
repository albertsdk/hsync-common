# HSYNC Common — Documentation

`hsync-common` is the shared library at the heart of the HSYNC ecosystem. It
provides the canonical data models, the versioned wire protocol, and the
cross-cutting utilities (hashing, compression, ignore rules, permissions, SSL,
logging) that the client, server, desktop, and Android apps all build on.

It is **not** a standalone application: there is nothing to install or run on its
own. It is consumed by the other projects as a Poetry path dependency and
mirrored in Kotlin by the Android app.

## Using the library

Add it as a path dependency from a sibling project (this is already wired in the
client, server, and desktop `pyproject.toml`):

```toml
[tool.poetry.dependencies]
hsync-common = { path = "../hsync-common", develop = true }
```

Then import the shared building blocks directly:

```python
from hsync_common.models import File, Dir
from hsync_common.protocol.handshake import PROTOCOL_VERSION_REST
```

## Where to start

- **New to hsync-common?** → Start with [Usage](usage.md) for an overview of how to integrate the library.
- **Understanding the shared models?** → Read the [Models guide](models.md).
- **Using the utilities?** → See the [Utilities guide](utilities.md).
- **Working with the protocol?** → Read the [Protocol guide](protocol.md).
- **Understanding authentication?** → The [Authentication](authentication.md) spec covers CID format, message schema, and protocol versioning shared by all components.
- **Implementing LAN P2P?** → The [LAN Protocol spec](lan-protocol.md) is the authoritative reference.
- **Reading logs?** → The [Log Labels reference](log-labels.md) catalogs every action label across all projects.
- **Working on the Android app?** → See [Android Mirroring](android-mirroring.md) for Kotlin/Python sync.
- **Why were these decisions made?** → The [Architecture Decision Records](internal/adr/README.md) document the rationale.
- **Contributing to the codebase?** → See the [Internal architecture](internal/architecture.md).

## Documentation map

| Document | What it covers |
| -------- | -------------- |
| [usage.md](usage.md) | How to integrate hsync-common as a dependency, import paths, versioning. |
| [models.md](models.md) | The shared data models: File, Dir, Symlink, Event, SyncAction, TombstoneStore, SyncStateStore, delta models. |
| [utilities.md](utilities.md) | Cross-cutting utilities: compression, hashing, ignore matcher, path validation, SSL, logging, clock, formatting, runtime detection. |
| [protocol.md](protocol.md) | Versioned wire protocol: handshake, capabilities, LAN election, pairing, JSON-Schemas, fixtures. |
| [authentication.md](authentication.md) | Shared authentication contracts: CID format, message schema, protocol version negotiation, cross-language enforcement. |
| [lan-protocol.md](lan-protocol.md) | The LAN discovery, master-election, pairing, and security specification (authoritative reference). |
| [log-labels.md](log-labels.md) | Canonical catalog of every action label across all projects: meaning, color category, and which project emits it. |
| [android-mirroring.md](android-mirroring.md) | How Python models are mirrored in Kotlin for the Android app. |
| [internal/architecture.md](internal/architecture.md) | Internal architecture — models, utilities, and the protocol package in detail. |
| [internal/adr/](internal/adr/README.md) | Architecture Decision Records — the *why* behind the ecosystem's stable, cross-project decisions. |

## Related projects

- [HSYNC Client](https://github.com/albertobasso/hsync-client/blob/main/README.md) - Sync client (Server Mode and LAN/P2P Mode)
- [HSYNC Server](https://github.com/albertobasso/hsync-server/blob/main/README.md) - Central synchronization server (Server Mode)
- [HSYNC Desktop](https://github.com/albertobasso/hsync-desktop/blob/main/docs/README.md) — Desktop client GUI front-end *(in development)*.
- [HSYNC Android](https://github.com/albertobasso/hsync-android/blob/main/docs/README.md) — Android client app *(in development)*.

> **Note:** The desktop GUI (`HSYNC Desktop`) and the Android app (`HSYNC Android`)
> are still under active development and are not yet ready for production use.
