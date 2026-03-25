# Protocol

`hsync-common` defines the versioned wire protocol shared by all HSYNC
consumers. This includes handshake negotiation, capability advertisement, LAN
election, pairing, and JSON-Schema contracts.

## Protocol versions

The protocol version is the single source of truth:

```python
from hsync_common.protocol.handshake import (
    PROTOCOL_VERSION_REST,
    PROTOCOL_VERSION_WS,
    PROTOCOL_VERSION_LAN,
)
```

Consumers advertise their supported version during connection setup. A mismatch
causes the connection to be refused.

## Capabilities

Peers advertise capabilities during the handshake:

- `compression` — zstd transfer support
- `delta` — rsync-style block sync support
- `vector_clocks` and `tombstones` — causal synchronization metadata
- `https` and `never_master` — LAN transport/election behavior
- `peer_download` — LAN inventory, batch source lookup, and read-only seeder
  semantics

The registry is `hsync_common.protocol.handshake.Capability`; the desktop-facing
capability document is in `hsync_common.protocol.capabilities`. Capabilities are
additive within a protocol version and are used only by intersection.

## WebSocket authentication

The first frame on a WebSocket connection must be an `auth` message:

```json
{"type": "auth", "token": "<account_token>", "protocol_version": "ws/1", "app_version": "1.0.0", "capabilities": []}
```

The server replies with `{"type": "auth", "status": "ok", ...}` on success, or
closes the connection with a specific error code on failure.

## LAN election & Pairing

LAN-specific protocol details (master election, TOFU pinning, strict pairing,
LAN-key write policy) are documented in the authoritative
[LAN Protocol specification](lan-protocol.md).

The canonical implementations live in:
- `hsync_common.protocol.lan` — election algorithm
- `hsync_common.protocol.pairing` — trust/pairing rules

## JSON-Schemas

Wire format contracts are generated as JSON-Schema and committed as golden
fixtures:

| Channel | Schema location |
|---------|-----------------|
| REST | `protocol/rest/openapi.json` |
| WebSocket | `protocol/ws/ws-schema.json` |
| LAN TXT | `protocol/lan/txt-schema.json` |
| LAN WebSocket | `protocol/lan/wss-schema.json` |
| LAN peer-source request/response | `protocol/lan/sources-schema.json` |

Cross-language parity tests (Python + Kotlin) require both implementations to
produce identical results before an ecosystem protocol change is complete.

## See also

- [LAN Protocol specification](lan-protocol.md) — detailed LAN discovery, election,
  pairing, and security specification.
- [Models guide](models.md) — data models used in protocol messages.
- [Internal architecture](internal/architecture.md) — detailed protocol package
  structure.
