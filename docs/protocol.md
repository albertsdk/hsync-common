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

- **Compression** — `zstd` support (via HTTP header or mDNS TXT record)
- **Delta transfer** — rsync-style block sync support
- **Protocol version** — REST, WebSocket, and LAN protocol versions

The canonical capability document is in `hsync_common.protocol.capabilities`.

## WebSocket authentication

The first frame on a WebSocket connection must be an `auth` message:

```json
{"type": "auth", "token": "<api_key>", "protocol_version": "ws/1", "app_version": "1.0.0", "capabilities": []}
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

Cross-language parity tests (Python + Kotlin) validate that both implementations
produce identical results.

## See also

- [LAN Protocol specification](lan-protocol.md) — detailed LAN discovery, election,
  pairing, and security specification.
- [Models guide](models.md) — data models used in protocol messages.
- [Internal architecture](internal/architecture.md) — detailed protocol package
  structure.
