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

- **Understanding the shared models?** → Read the [Architecture](architecture.md) overview.
- **Implementing LAN P2P?** → The [LAN Protocol spec](LAN_PROTOCOL.md) is the authoritative reference.
- **Working on the Android app?** → See [Android Mirroring](android-mirroring.md) for Kotlin/Python sync.
- **Why were these decisions made?** → The [Architecture Decision Records](adr/README.md) document the rationale.

## Documentation map

| Document | What it covers |
| -------- | -------------- |
| [architecture.md](architecture.md) | Models, utilities, and the protocol package; how the wire contract is generated and kept in sync. |
| [LAN_PROTOCOL.md](LAN_PROTOCOL.md) | The LAN discovery, master-election, pairing, and security specification (authoritative reference). |
| [android-mirroring.md](android-mirroring.md) | How Python models are mirrored in Kotlin for the Android app. |
| [adr/README.md](adr/README.md) | Architecture Decision Records — the *why* behind the ecosystem's stable, cross-project decisions. |

## Related projects

- [hsync-client](https://github.com/albertobasso/hsync-client/blob/main/docs/README.md) — the sync client / CLI.
- [hsync-server](https://github.com/albertobasso/hsync-server/blob/main/docs/README.md) — the central server.
- [hsync-desktop](https://github.com/albertobasso/hsync-desktop/blob/main/docs/README.md) — the desktop GUI *(in development)*.
- [hsync-android](https://github.com/albertobasso/hsync-android/blob/main/docs/README.md) — the Android app *(in development)*.

> **Note:** The desktop GUI (`hsync-desktop`) and the Android app (`hsync-android`)
> are still under active development and are not yet ready for production use.
