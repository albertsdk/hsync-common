# ADR 0008 — Single shared API key authentication

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

The server needs to authenticate clients before allowing any operation (upload,
download, list, WebSocket). HSYNC is designed for a small number of trusted
devices owned by a single person or family — not a multi-tenant SaaS. The
authentication mechanism must be:

- **Simple to configure**: one secret, set once, done.
- **Cross-platform**: the Python CLI, desktop GUI, and Android app must all
  support it with minimal code.
- **Sufficiently secure** for the threat model (network eavesdropper, not
  multi-tenant isolation).

Options considered:

- **Per-user credentials with database** — overkill for a single-user system;
  adds migration, password reset, and DB dependency.
- **OAuth 2.0 / OIDC** — requires an identity provider and token refresh logic
  on every client, including Android. Massive complexity for no benefit in a
  single-tenant deployment.
- **TLS client certificates** — strong, but certificate management on Android
  and non-technical users is painful.
- **Single shared Bearer token** — one secret, all clients use it, verified via
  constant-time HMAC comparison.

## Decision

We will authenticate all API requests with a **single shared API key** passed as
a `Bearer` token in the `Authorization` header:

- The key is set via `HSYNC_API_KEY` environment variable on the server.
- Verification uses `hmac.compare_digest` (constant-time) to prevent timing
  attacks on the secret.
- There is **no user concept, no roles, no scopes** — every authenticated client
  has full access to all buckets.
- The key is masked in logs (`abc****xyz` format) to prevent accidental
  exposure.
- The health endpoint (`/health`) is unauthenticated for monitoring.

Alternatives rejected:

- **OAuth/OIDC**: adds identity provider dependency, token refresh logic, and
  significant client-side complexity for zero security gain in a single-tenant
  deployment.
- **TLS client certificates**: strong but operationally painful — certificate
  provisioning on Android, renewal, and explaining PKI to non-technical users is
  not worth the security margin over Bearer+HMAC over HTTPS.
- **Per-device API keys**: would require key management UI and a database; the
  "revoke one device" use case is rare enough that rotating the single key is
  acceptable.

## Consequences

- **Setup is trivial**: one `openssl rand -base64 32` command, paste into
  `prod.env`, done.
- **No multi-tenancy**: the server cannot serve multiple independent users with
  different keys. This is a deliberate trade-off — if multi-tenancy is ever
  needed, a reverse proxy with per-user routing to separate server instances is
  the intended approach.
- **Revocation is coarse**: changing the key disconnects *all* clients. In
  practice this is acceptable because all clients are owned by the same person
  and can be updated simultaneously.
- **The key travels over HTTPS only** — the deployment guide mandates a reverse
  proxy terminating TLS; plain HTTP is for LAN/testing only.

## See also

- [ADR-0001](0001-server-vs-lan-modes.md) — LAN mode uses TOFU pinning, not the
  shared API key.
- [Deployment Guide](https://github.com/albertobasso/hsync-server/blob/main/docs/deployment.md) —
  key generation instructions.
