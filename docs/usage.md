# Using hsync-common

`hsync-common` is a Python library — it is not a standalone application. You
consume it as a Poetry path dependency from one of the consumer projects
(`hsync-client`, `hsync-server`, `hsync-desktop`).

## Adding the dependency

```toml
[tool.poetry.dependencies]
hsync-common = { path = "../hsync-common", develop = true }
```

This is already wired in every consumer's `pyproject.toml`.

## Importing

Import the shared building blocks directly from `hsync_common`:

```python
from hsync_common.models import File, Dir, Event, SyncAction
from hsync_common.protocol.handshake import PROTOCOL_VERSION_REST
from hsync_common.compression import compress_data, decompress_data
from hsync_common.ignore import IgnoreMatcher
```

There are no compatibility shims or re-export modules — always import from the
canonical location.

## Versioning

The library version is the single source of truth for the wire protocol:

```python
from hsync_common.constants import HSYNC_VERSION
# → "1.0.0"
```

A protocol version change in `hsync-common` is applied atomically across all
consumers. See the [Protocol guide](protocol.md) for version negotiation.

## What's available

| Area | Package | Documentation |
|------|---------|---------------|
| Data models | `hsync_common.models` | [Models guide](models.md) |
| Wire protocol | `hsync_common.protocol` | [Protocol guide](protocol.md) |
| Utilities | `hsync_common.*` | [Utilities guide](utilities.md) |

## See also

- [Models guide](models.md) — File, Dir, Event, SyncAction, TombstoneStore, etc.
- [Utilities guide](utilities.md) — compression, hashing, ignore, path validation, SSL, logging.
- [Protocol guide](protocol.md) — handshake, capabilities, p2p election, pairing.
- [Internal architecture](internal/architecture.md) — detailed package structure.
