# Authentication — Shared Contracts

This document specifies the canonical contracts shared by every HSYNC component
that authenticates a remote peer. It covers the wire format of authentication
messages, the client-ID (CID) format, and the protocol-version negotiation.
Transport-specific flows (Server Mode, LAN P2P with/without `LAN_KEY`) are
documented in the consuming projects:

- **Server-side**: [`hsync-server/docs/authentication.md`](https://github.com/albertobasso/hsync-server/blob/main/docs/authentication.md)
- **Client-side**: [`hsync-client/docs/authentication.md`](https://github.com/albertobasso/hsync-client/blob/main/docs/authentication.md)

## Client ID (CID) format

Every HSYNC peer is identified by a **CID** — a strictly alphanumeric NanoID-style
string. The canonical pattern is enforced by `hsync_common.models.event.is_valid_cid`:

```
^[A-Za-z0-9]{1,64}$
```

| Property | Value |
|---|---|
| Alphabet | `A-Z a-z 0-9` (62 symbols) |
| Min length | 1 |
| Max length | 64 |
| Match mode | **fullmatch** (not `match` — trailing `\n` is rejected) |
| Default length | 21 characters (~125 bits of entropy) |
| Python validator | `hsync_common.models.event.is_valid_cid(value)` |
| Kotlin validator | `CID_PATTERN.matcher(value).matches()` in `LanWebSocketServer` / `LanServer` |

A CID that fails validation **must be rejected at the transport level** (WebSocket
close with `reason: "invalid_cid"`, or HTTP 4xx) — never silently replaced with a
fallback. This prevents log injection and guarantees every CID-bearing log line is
safe to parse.

## Authentication message schema

All HSYNC authentication handshakes use JSON text frames over the WebSocket
connection (there is no separate auth channel). The message envelope is:

```json
{
  "type": "<message-type>",
  "status": "<ok|failed>",
  "token": "<shared-secret>",
  "cid": "<client-id>",
  "app_version": "<semver>",
  "protocol_version": "<protocol-version>",
  "capabilities": ["compression", "delta", ...],
  "reason": "<error-detail>"
}
```

### Defined `type` values

| `type` | Direction | Meaning |
|---|---|---|
| `auth` | Client → Server / Slave → Master | Authentication request carrying the shared secret and CID |
| `auth_required` | Master → Slave | Server requires authentication (LAN P2P with `LAN_KEY`) |
| `hello` | Master → Slave | Lightweight handshake: master has no `LAN_KEY`, asks slave for its CID for logging |
| `connected` | Master → Slave | Legacy greeting (pre-hello); no auth required |

### Response `status` values

| `status` | Meaning |
|---|---|
| `ok` | Authentication succeeded |
| `failed` | Authentication failed (wrong token, malformed CID, expired, etc.) |

When `status` is `"failed"`, the optional `reason` field carries a machine-readable
error code (e.g. `"invalid_cid"`, `"protocol_mismatch"`, `"unauthorized"`).

## Protocol version negotiation

Every connection begins with a protocol version exchange. The client advertises
its supported protocol version in the initial auth frame; the server replies with
its own version in the auth response. A mismatch where the server version is
outside the client's compatibility range is a **hard failure** — the connection is
closed with `reason: "protocol_mismatch"`.

Protocol versions are defined in `hsync_common.protocol.handshake`:
- `PROTOCOL_VERSION_REST` — REST API version
- `PROTOCOL_VERSION_WS` — WebSocket protocol version

## CID propagation

Once a peer's CID has been validated and (where applicable) authenticated, it is:

1. **Logged** on every connection/disconnection event
2. **Sent with HTTP requests** (query param `?cid=`) on upload, delete, rename, and directory creation, so the receiving peer can attribute the resulting filesystem event for echo suppression
3. **Embedded in broadcast events** (`"cid"` field) so the originator can recognize and discard its own echo

### Authenticated vs unauthenticated CID

| Scenario | CID validated? | CID authenticated? | Can be used for echo suppression? | Logged as |
|---|---|---|---|---|
| Server Mode (API key) | ✅ `is_valid_cid()` | ✅ (by API key) | ✅ | `(CID: xxx)` |
| LAN P2P with `LAN_KEY` | ✅ `is_valid_cid()` | ✅ (`hmac.compare_digest`) | ✅ | `(CID: xxx)` |
| LAN P2P without `LAN_KEY` (hello) | ✅ `is_valid_cid()` | ❌ (no shared secret) | ❌ (master's own CID used instead) | `(CID: xxx, unauthenticated)` |

## Cross-language enforcement

Both the Python (`hsync_common`) and Kotlin (`hsync-android`) codebases enforce
the same CID pattern and validation logic. The pattern and its rationale are
documented in:

- Python: `hsync_common/models/event.py` — `CID_PATTERN`, `is_valid_cid()`
- Kotlin: `LanWebSocketServer.kt` — `CID_PATTERN`, `isValidCid()` (companion object)
- Kotlin: `LanServer.kt` — `CID_PATTERN`, `isValidCidFormat()` (companion object)
