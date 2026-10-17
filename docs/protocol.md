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
    PROTOCOL_VERSION_P2P,
)
```

Consumers advertise their supported version during connection setup. A mismatch
causes the connection to be refused.

The `boot/1` bootstrap channel (QUIC/UDP, ALPN `hsync-boot/1`) is specified
canonically in `hsync-bootnode` and mirrored for the client in
`hsync_common/protocol/bootnode.py` (`PROTOCOL_VERSION_BOOT`); it is advertised
alongside the others as `protocol_version.boot` in the capabilities document.
See [Boot/1 bootstrap protocol](bootnode-protocol.md).

## Capabilities

Peers advertise capabilities during the handshake:

- `compression` — zstd transfer support
- `delta` — rsync-style block sync support
- `vector_clocks` and `tombstones` — causal synchronization metadata
- `https` and `never_master` — p2p transport/election behavior
- `peer_download` — p2p inventory, batch source lookup, and read-only seeder
  semantics

The registry is `hsync_common.protocol.handshake.Capability`; the desktop-facing
capability document is in `hsync_common.protocol.capabilities`. Capabilities are
optional within a protocol version and are used only by intersection.

## WebSocket authentication

The first frame on a WebSocket connection must be an `auth` message:

```json
{
  "type": "auth",
  "token": "ACCOUNT_TOKEN",
  "protocol_version": "ws/1",
  "app_version": "1.0.0",
  "capabilities": []
}
```

The server replies with `{"type": "auth", "status": "ok", ...}` on success, or
closes the connection with a specific error code on failure.

## p2p election & Pairing

p2p-specific protocol details (master election, TOFU pinning, strict pairing,
p2p-key write policy) are documented in the authoritative
[p2p Protocol specification](p2p-protocol.md).

The canonical implementations live in:
- `hsync_common.protocol.p2p` — election algorithm
- `hsync_common.protocol.pairing` — trust/pairing rules

## JSON-Schemas

Wire format contracts are generated as JSON-Schema and committed as golden
fixtures:

| Channel | Schema location |
|---------|-----------------|
| REST | `protocol/rest/openapi.json` |
| WebSocket | `protocol/ws/ws-schema.json` |
| p2p TXT | `protocol/p2p/txt-schema.json` |
| p2p WebSocket | `protocol/p2p/wss-schema.json` |
| p2p peer-source request/response | `protocol/p2p/sources-schema.json` |

Cross-language parity tests (Python + Kotlin) require both implementations to
produce identical results before an ecosystem protocol change is complete.

## See also

- [p2p Protocol specification](p2p-protocol.md) — detailed p2p discovery, election,
  pairing, and security specification.
- [Models guide](models.md) — data models used in protocol messages.
- [Internal architecture](internal/architecture.md) — detailed protocol package
  structure.
