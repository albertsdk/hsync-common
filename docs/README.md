# HSYNC Common — Documentation

`hsync-common` is the shared library at the heart of the HSYNC ecosystem. It
provides the canonical data models, the versioned wire protocol, and the
cross-cutting utilities (hashing, compression, ignore rules, permissions, SSL,
logging) that the client, server, desktop, and Android apps all build on.

It is **not** a standalone application: there is nothing to install or run on its
own. It is consumed by the other projects as a Poetry path dependency and
mirrored in Kotlin by the Android app.

## Using the library

Add the path dependency and import the shared building blocks as shown in the
[Usage guide](usage.md) — that page is the single source for the integration
snippet.

## What do you want to do?

- **Integrate hsync-common into a project?** → [Usage](usage.md) (Tutorial)
- **Read or exchange data models?** → [Models guide](models.md) (Reference)
- **Use a utility (compression, hashing, SSL, ignore…)?** → [Utilities guide](utilities.md) (Reference)
- **Check a canonical value or constant?** → [Constants reference](constants.md) (Reference)
- **Speak or extend the wire protocol?** → [Protocol guide](protocol.md) (Reference)
- **Implement or debug p2p?** → [p2p Protocol spec](p2p-protocol.md) (Specification, authoritative)
- **Discover peers across networks?** → [Boot/1 bootstrap protocol](bootnode-protocol.md) (Reference, mirror of the canonical spec)
- **Understand authentication contracts?** → [Authentication](authentication.md) (Specification)
- **Understand delta transfer?** → [Delta transfer guide](delta.md) (Explanation)
- **Configure ignore rules?** → [Ignore file guide](ignore-file.md) (Reference)
- **Decode the client/server logs?** → [Log Labels reference](log-labels.md) (Reference)
- **Keep the Android app in sync with Python?** → [Android Mirroring](android-mirroring.md) (Explanation)
- **Understand why a decision was made?** → [Architecture Decision Records](internal/adr/README.md)
- **Contribute to the codebase?** → [Internal architecture](internal/architecture.md)

## Documentation map

| Document | What it covers |
| -------- | -------------- |
| [usage.md](usage.md) | How to integrate hsync-common as a dependency, import paths, versioning. |
| [models.md](models.md) | The shared data models: File, Dir, Symlink, Event, SyncAction, TombstoneStore, SyncStateStore, delta models. |
| [bootnode-protocol.md](bootnode-protocol.md) | The `boot/1` bootstrap channel as mirrored for the client: frames, `capacity`/`reachable`, bucket tokens. |
| [utilities.md](utilities.md) | Cross-cutting utilities: compression, hashing, path validation, SSL, logging, clock, formatting, runtime detection. |
| [protocol.md](protocol.md) | Versioned wire protocol: handshake, capabilities, p2p election, pairing, JSON-Schemas, fixtures. |
| [authentication.md](authentication.md) | Shared authentication contracts: CID format, message schema, protocol version negotiation, cross-language enforcement. |
| [p2p-protocol.md](p2p-protocol.md) | The p2p discovery, master-election, pairing, and security specification (authoritative reference). |
| [log-labels.md](log-labels.md) | Canonical catalog of every action label across all projects: meaning, color category, and which project emits it. |
| [ignore-file.md](ignore-file.md) | `.hsyncignore` syntax, three-layer matching, IgnoreMatcher API reference, hot-reload, ReDoS protection. |
| [constants.md](constants.md) | Canonical constants: version, sentinel filenames, chunk sizes, delta transfer thresholds. |
| [delta.md](delta.md) | Rsync-style block-level delta transfer: decision heuristics, rolling checksum engine, matching, reconstruction. |
| [android-mirroring.md](android-mirroring.md) | How Python models are mirrored in Kotlin for the Android app. |
| [internal/architecture.md](internal/architecture.md) | Internal architecture — models, utilities, and the protocol package in detail. |
| [internal/adr/](internal/adr/README.md) | Architecture Decision Records — the *why* behind the ecosystem's stable, cross-project decisions. |

## Associated Ecosystem Components

- [HSYNC Client](https://github.com/albertsdk/hsync-client/blob/main/README.md) - Sync client (Server Mode and p2p Mode)
- [HSYNC Server](https://github.com/albertsdk/hsync-server/blob/main/README.md) - Central synchronization server (Server Mode)
- [HSYNC Desktop](https://github.com/albertsdk/hsync-desktop/blob/main/docs/README.md) — Desktop client GUI front-end *(in development)*.
- [HSYNC Android](https://github.com/albertsdk/hsync-android/blob/main/docs/README.md) — Android client app *(in development)*.

> **Note:** The desktop GUI (`HSYNC Desktop`) and the Android app (`HSYNC Android`)
> are still under active development and are not yet ready for production use.
