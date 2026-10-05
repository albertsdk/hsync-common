# Authentication — Shared Contracts

This document specifies the canonical contracts shared by every HSYNC component
that authenticates a remote peer. It covers the wire format of authentication
messages, the client-ID (CID) format, and the protocol-version negotiation.
Transport-specific flows (Server Mode, p2p with/without `P2P_KEY`) are
documented in the consuming projects:

- **Server-side**: [`hsync-server/docs/authentication.md`](https://github.com/albertsdk/hsync-server/blob/main/docs/authentication.md)
- **Client-side**: [`hsync-client/docs/authentication.md`](https://github.com/albertsdk/hsync-client/blob/main/docs/authentication.md)

## What is a CID?

A **CID** (Client ID) is an **ephemeral session identifier** generated locally
by each HSYNC peer at startup. It is **never assigned by a server** — every
peer (desktop client, Android client, server-mode peer acting as a client)
creates its own cryptographically random CID on launch and discards it on
shutdown.

The CID serves three purposes across the protocol:

1. **Echo suppression** — every filesystem event broadcast carries the
   originator's CID. A peer that receives its own CID back from the relay
   (server or p2p master) silently discards the event, preventing an
   infinite echo loop.

2. **Event attribution** — log lines and debug output tag each operation
   with the originating CID, making it possible to trace which peer
   triggered which sync action.

3. **Master election tiebreaker** — in p2p mode, when two peers start at
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
| **Authenticity** | May be authenticated (bound to a shared `API_KEY` or `P2P_KEY`) or unauthenticated (hello mode) |

### Authenticated vs unauthenticated CID

A CID alone is not a proof of identity. Its trustworthiness depends on the
transport context:

- **Server Mode**: the CID arrives alongside a validated account token → **authenticated**.
  The account token (`hs_<account_id>_<secret>`) identifies a server-side account
  with a role (`admin` or `client`) and bucket memberships. The CID remains
  ephemeral and is not the account id.
- **p2p with `P2P_KEY`**: the CID is bound to the shared secret → **authenticated**.
- **p2p without `P2P_KEY` (hello mode)**: the CID is self-declared and
  unverified → **unauthenticated** — the master ignores it for echo suppression
  and qualifies it in logs.

The distinction matters for security: an unauthenticated CID must never be
trusted for event attribution or origin tracking, since any host on the LAN
can advertise any CID. See the table in [CID propagation](#cid-propagation).

## CID format

Every HSYNC peer is identified by a **CID** — a strictly alphanumeric
string. The canonical pattern is enforced by `hsync_common.models.event.is_valid_cid`:

```text
^[A-Za-z0-9]{21}$
```

| Property | Value |
|---|---|
| Alphabet | `A-Z a-z 0-9` (62 symbols) |
| Length | 21 (fixed) |
| Match mode | **fullmatch** (not `match` — trailing `\n` is rejected) |
| Entropy | ~125 bits (log₂(62²¹)) |
| Python validator | `hsync_common.models.event.is_valid_cid(value)` (`^[A-Za-z0-9]{21}$`) |
| Kotlin validator | `CID_PATTERN.matcher(value).matches()` in `P2PWebSocketServer` / `P2PServer` (`^[A-Za-z0-9]{21}$`) |

A CID that fails validation **must be rejected at the transport level** (WebSocket
close with `reason: "invalid_cid"`, or HTTP 4xx) — never silently replaced with a
fallback. This prevents log injection and guarantees every CID-bearing log line is
safe to parse.

## Authentication message schema

All HSYNC authentication handshakes use JSON text frames over the WebSocket
connection (there is no separate auth channel). The message envelope is:

```json
{
  "type": "MESSAGE_TYPE",
  "status": "OK_OR_FAILED",
  "token": "ACCOUNT_TOKEN",
  "cid": "CLIENT_ID",
  "app_version": "SEMVER",
  "protocol_version": "PROTOCOL_VERSION",
  "capabilities": ["compression", "delta", ...],
  "reason": "ERROR_DETAIL"
}
```

### Defined `type` values

| `type` | Direction | Meaning |
|---|---|---|
| `auth` | Client → Server / Slave → Master | Authentication request carrying the account token (Server Mode) or shared p2p key, and CID |
| `auth_required` | Master → Slave | Master requires authentication (p2p with `P2P_KEY`) |
| `hello` | Master → Slave | Lightweight handshake: master has no `P2P_KEY`, asks slave for its CID for logging |

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
| Server Mode (account token) | ✅ `is_valid_cid()` | ✅ (by account token) | ✅ | `(CID: xxx)` |
| p2p with `P2P_KEY` | ✅ `is_valid_cid()` | ✅ (`hmac.compare_digest`) | ✅ | `(CID: xxx)` |
| p2p without `P2P_KEY` (hello) | ✅ `is_valid_cid()` | ❌ (no shared secret) | ❌ (master's own CID used instead) | `(CID: xxx, unauthenticated)` |

## Cross-language enforcement

Both the Python (`hsync_common`) and Kotlin (`hsync-android`) codebases enforce
the same CID pattern and validation logic. The pattern and its rationale are
documented in:

- Python: `hsync_common/models/event.py` — `CID_PATTERN`, `is_valid_cid()`
- Kotlin: `P2PWebSocketServer.kt` — `CID_PATTERN`, `isValidCid()` (companion object)
- Kotlin: `P2PServer.kt` — `CID_PATTERN`, `isValidCidFormat()` (companion object)

## Server Mode account model

In Server Mode, authentication uses **per-account tokens** (not a shared key).
Each account has a stable id, a revocable secret, a role, and bucket memberships.

### Token format

```text
hs_<account_id 21 alnum>_<secret 64 hex>
```

- `hs_` prefix (opaque, not parseable by clients).
- `account_id`: 21-char alphanumeric, server-minted, immutable. Identifies the
  account. Not the same as the session CID (which is ephemeral and client-minted).
- `secret`: 64-char lowercase hex (`secrets.token_hex(32)`).

The token is presented as `Authorization: Bearer <token>` (REST) and as the
`token` field of the WS `auth` frame. The wire envelope is identical to the
previous shared-key model — clients treat the token as an opaque string.

### Roles

| Role | Bucket access | Account management |
|---|---|---|
| `admin` | All buckets | Create, rotate, disable, delete accounts; grant/revoke membership; transfer ownership |
| `client` | Owns + member buckets only | None |

### Bucket membership

- Each bucket has exactly one **owner** and zero or more **members**.
- Owner and member have the same data access (read, write, sync).
- Only admin or the bucket owner can grant/revoke membership and transfer ownership.
- Bucket deletion is admin-only.

### Bootstrap

On first start (empty account store), an admin account is created:
- If `HSYNC_ADMIN_KEY` (64 hex) is set: used silently as the admin secret.
- If absent: a secret is generated and the full token `hs_<id>_<secret>` is
  printed once (not recoverable).

### Anti-enumeration

- Unknown account id → dummy scrypt (same timing as a real verify).
- Disabled / expired / non-member → same wire response as "invalid key" (401 /
  WS 4003) or "bucket not found" (404 / WS 4009).
