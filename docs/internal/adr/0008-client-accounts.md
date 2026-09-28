# ADR 0008 — Client accounts, roles and bucket membership

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

The server needs to authenticate distinct clients with separate, individually
revocable identities, and to allow two or more clients to synchronize the same
bucket via explicit membership grants. HSYNC is designed for a small number of
trusted devices (phone, laptop, NAS) owned by a single person or family — not a
multi-tenant SaaS. The authentication mechanism must be:

- **Per-client**: each device has its own key, revocable without affecting others.
- **Role-aware**: an administrator role can manage accounts and operate on all
  buckets; a client role operates only on buckets it owns or is a member of.
- **Cross-platform**: the Python CLI, desktop GUI, and Android app must all
  support it with minimal code changes (the wire format stays `Bearer <token>`).
- **Self-contained**: no external database or identity provider — all auth state
  lives in the server's global auth DB (`<state_dir>/server/auth.db`).

Options considered:

- **Single shared API key** — simple but coarse: revoking one device disconnects
  all, and there is no way to restrict bucket access per client.
- **OAuth 2.0 / OIDC** — requires an identity provider and token refresh logic
  on every client, including Android. Massive complexity for no benefit in a
  single-tenant deployment.
- **TLS client certificates** — strong, but certificate management on Android
  and non-technical users is painful.
- **Account-based tokens with bucket membership** — MinIO/S3-style identity
  (stable account id, per-account secret, admin role, bucket ownership/membership)
  adapted to a single-tenant installation without an external DB.

## Decision

We will authenticate API requests with **per-account tokens** and authorize
bucket access via **explicit membership**:

- **Token format**: `hs_<account_id 21 alnum>_<secret 64 hex>`. The account id
  is opaque, server-minted, and immutable. The secret is `secrets.token_hex(32)`.
  The token is presented as `Authorization: Bearer <token>` (REST) and as the
  `token` field of the WS `auth` frame — the wire envelope is unchanged.
- **Account store**: `clients` table on the global auth DB (server-only schema,
  not in the common `sqlstore`). Fields: id, name (UNIQUE, immutable), role
  (`admin` | `client`), status (`active` | `disabled`), PHC-style scrypt hash,
  key prefix (8 hex for logs), key generation, expiry, prior-key (grace), timestamps.
- **Membership**: `bucket_members` table `(bucket, client_id, role)` with exactly
  one owner per bucket (partial UNIQUE index). Admin bypasses membership.
- **Hashing**: scrypt (N=2^17, r=8, p=1) PHC-style at rest; secret in clear only
  at emission. KDF cache (SHA-256(token) → account_id + generation) avoids
  re-hashing on every request; a DB SELECT re-checks status/generation/expiry.
- **Bootstrap**: on first start (empty `clients`), an admin account is created
  from `HSYNC_ADMIN_KEY` (64 hex, silent) or generated and printed once.
- **Anti-enumeration**: unknown account_id triggers a dummy scrypt; disabled /
  expired / non-member all return the same wire response as "invalid key" (REST
  401, WS 4003) or "bucket not found" (REST 404, WS 4009).
- **CLI**: `hsync-server admin` operates directly on the store (filesystem
  authority, no key required) for account CRUD, membership, and recovery.
- **WS revocation**: eager close on the local worker; cross-worker re-check on
  every inbound frame, every ping, and before every broadcast send.

Alternatives rejected:

- **OAuth/OIDC**: adds identity provider dependency, token refresh logic, and
  significant client-side complexity for zero security gain in a single-tenant
  deployment.
- **TLS client certificates**: strong but operationally painful — certificate
  provisioning on Android, renewal, and explaining PKI to non-technical users is
  not worth the security margin over Bearer+scrypt over HTTPS.
- **Single shared key**: cannot revoke per-device or restrict bucket access.

## Consequences

- **Per-client revocation**: rotating or disabling one account does not affect
  others. The `key_generation` field binds WS sessions to a specific key version.
- **Bucket isolation**: a client sees only its own and shared buckets; all others
  return 404 (indistinguishable from "not found").
- **No multi-tenancy**: the server serves one installation. Multi-tenant is via
  separate server instances behind a reverse proxy.
- **Admin recovery**: if the admin key is lost, `hsync-server admin client
  rotate-key --name admin` from the host filesystem recovers access.
- **The token travels over HTTPS only** — the deployment guide mandates a reverse
  proxy terminating TLS; plain HTTP is for LAN/testing only.
- **`HSYNC_API_KEY` (client-side)** remains the env var name that holds the
  account token on the client; the server uses `HSYNC_ADMIN_KEY` for bootstrap only.

## See also

- [ADR-0001](0001-server-vs-p2p-modes.md) — p2p mode uses TOFU pinning, not
  account tokens.
- [ADR-0012](0012-rate-limiting.md) — rate limiting is per-IP; admin endpoints
  have a stricter limit.
- [Deployment Guide](https://github.com/albertsdk/hsync-server/blob/main/docs/deployment.md) —
  key generation and bootstrap instructions.
