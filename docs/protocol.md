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
{"type": "auth", "token": "<api_key>", "version": "1.0.0"}
```

The server replies with `{"type": "auth", "status": "ok", ...}` on success, or
closes the connection with a specific error code on failure.

## LAN election

LAN mode peers elect a master using a deterministic algorithm
(`elect_master` in `hsync_common.protocol.lan`). The winner is the candidate
with the highest priority:

1. **`server_ready`** — an already-serving incumbent wins.
2. **`force_master`** — an operator-pinned master wins over ordinary peers.
3. **Bidirectional `sync_direction`** — preferred over upload-/download-only.
4. **Earliest `startup_time`** — the node that started first wins.
5. **Lowest `cid`** — deterministic final tiebreaker.

Peers with `never_master` are excluded from the candidate pool.

## Pairing

Trust is established via Trust On First Use (TOFU) with optional strict pairing.
The canonical rules are in `hsync_common.protocol.pairing`:

- `evaluate_pin` — classifies a certificate fingerprint as `trusted`, `matched`,
  `changed`, or `missing`.
- `lan_write_requires_key` — determines whether a shared key is required for
  write operations.
- `requires_pairing_confirmation` — determines whether strict pairing requires
  out-of-band confirmation.

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
