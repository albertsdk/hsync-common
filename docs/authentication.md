# Authentication — Shared Contracts

This document specifies the canonical contracts shared by every HSYNC component
that authenticates a remote peer. It covers the wire format of authentication
messages, the client-ID (CID) format, and the protocol-version negotiation.
Transport-specific flows (Server Mode, LAN P2P with/without `LAN_KEY`) are
documented in the consuming projects:

- **Server-side**: [`hsync-server/docs/authentication.md`](https://github.com/albertobasso/hsync-server/blob/main/docs/authentication.md)
- **Client-side**: [`hsync-client/docs/authentication.md`](https://github.com/albertobasso/hsync-client/blob/main/docs/authentication.md)

## What is a CID?

A **CID** (Client ID) is an **ephemeral session identifier** generated locally
by each HSYNC peer at startup. It is **never assigned by a server** — every
peer (desktop client, Android client, server-mode peer acting as a client)
creates its own cryptographically random CID on launch and discards it on
shutdown.

The CID serves three purposes across the protocol:

1. **Echo suppression** — every filesystem event broadcast carries the
   originator's CID. A peer that receives its own CID back from the relay
   (server or LAN master) silently discards the event, preventing an
   infinite echo loop.

2. **Event attribution** — log lines and debug output tag each operation
   with the originating CID, making it possible to trace which peer
   triggered which sync action.

3. **Master election tiebreaker** — in LAN mode, when two peers start at
   exactly the same `startup_time` (same-second), the peer with the
   lexicographically **lowest CID** wins the election. This is a
   deterministic, always-available fallback.

Key properties:

| Property | Detail |
|---|---|
| **Lifetime** | Ephemeral — regenerated on every restart |
| **Origin** | Generated locally (Python: `get_cid()`, Kotlin: `ClientId.newClientId()`) |
| **Secrecy** | Not a secret — the CID is broadcast openly on mDNS and embedded in every event |
| **Uniqueness** | Statistically unique per session (~125 bits of entropy) |
| **Authenticity** | May be authenticated (bound to a shared `API_KEY` or `LAN_KEY`) or unauthenticated (hello mode) |

### Authenticated vs unauthenticated CID

A CID alone is not a proof of identity. Its trustworthiness depends on the
transport context:

- **Server Mode**: the CID arrives alongside a validated `API_KEY` → **authenticated**.
- **LAN P2P with `LAN_KEY`**: the CID is bound to the shared secret → **authenticated**.
- **LAN P2P without `LAN_KEY` (hello mode)**: the CID is self-declared and
  unverified → **unauthenticated** — the master ignores it for echo suppression
  and qualifies it in logs.

The distinction matters for security: an unauthenticated CID must never be
trusted for event attribution or origin tracking, since any host on the LAN
can advertise any CID. See the table in [CID propagation](#cid-propagation).

## CID format

Every HSYNC peer is identified by a **CID** — a strictly alphanumeric
string. The canonical pattern is enforced by `hsync_common.models.event.is_valid_cid`:

```
^[A-Za-z0-9]{21}$
```

| Property | Value |
|---|---|
| Alphabet | `A-Z a-z 0-9` (62 symbols) |
| Length | 21 (fixed) |
| Match mode | **fullmatch** (not `match` — trailing `\n` is rejected) |
| Entropy | ~125 bits (log₂(62²¹)) |
| Python validator | `hsync_common.models.event.is_valid_cid(value)` (`^[A-Za-z0-9]{21}$`) |
| Kotlin validator | `CID_PATTERN.matcher(value).matches()` in `LanWebSocketServer` / `LanServer` (`^[A-Za-z0-9]{21}$`) |

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
