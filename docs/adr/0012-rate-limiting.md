# ADR 0012 — Tiered per-IP rate limiting

- **Status:** Accepted
- **Date:** 2026-07-02

## Context

The server exposes a public HTTP API that is vulnerable to abuse: a malicious or
buggy client could flood uploads, exhaust disk space, saturate bandwidth, or
open thousands of WebSocket connections. Rate limiting is essential for
availability and fair resource allocation.

The server has no user accounts ([ADR-0008](0008-single-api-key-auth.md)), so
limiting must be per-IP. Different endpoints have different costs and risk
profiles:

- **Uploads** are the most expensive (disk I/O, SHA-256, potential disk
  exhaustion) — should be the most restricted.
- **Downloads** are cheaper (read-only, kernel-cached) — can be more permissive.
- **General API** (list, delete, bucket ops) — moderate cost.
- **WebSocket connections** — long-lived, consume memory and file descriptors.
- **WebSocket messages** — high-frequency within a connection; a spammy client
  could flood event handlers.

A single global limit would either be too restrictive for downloads or too loose
for uploads.

## Decision

We will use **tiered per-IP rate limiting** via the `slowapi` library (which
builds on `limits` and integrates with FastAPI middleware):

- **Tiers** (configurable via environment variables):
  - `HSYNC_RATE_LIMIT_DEFAULT`: 500/minute — list, delete, bucket operations.
  - `HSYNC_RATE_LIMIT_UPLOAD`: 200/minute — file uploads (most restricted due to
    resource cost).
  - `HSYNC_RATE_LIMIT_DOWNLOAD`: 1000/minute — file downloads (most permissive,
    read-only).
  - `HSYNC_RATE_LIMIT_WEBSOCKET`: 50/minute — WebSocket connection upgrades.
  - `HSYNC_RATE_LIMIT_WS_MESSAGES`: 10/second — per-connection WebSocket event
    messages.
- **Reverse proxy handling**: `HSYNC_TRUSTED_PROXIES` defines a list of trusted
  reverse-proxy IPs. `X-Forwarded-For` is honoured **only** when the direct peer
  is in this list; otherwise the header is ignored to prevent IP spoofing and
  rate-limit bypass.
- Limiting uses **token bucket** algorithm (burst allowance with sustained rate
  enforcement) provided by `slowapi`.

Alternatives rejected:

- **No rate limiting**: leaves the server vulnerable to DoS by a single
  misbehaving client.
- **Single global limit**: fails to account for the asymmetric cost of different
  operations.
- **Per-bucket limiting**: adds complexity with no clear benefit — all buckets
  share the same disk and network, so per-IP is the right granularity.
- **Custom token bucket implementation**: `slowapi` is a well-tested FastAPI
  integration; reinventing it adds maintenance burden.

## Consequences

- **Fairness**: a client uploading large files cannot starve another client
  listing directories or downloading.
- **Per-IP granularity** means clients behind NAT share a limit — acceptable for
  HSYNC's single-user/small-family target, but a limitation if ever deployed in
  multi-user NAT environments.
- **Trusted proxy list must be maintained** — if the reverse proxy IP changes,
  rate limiting silently falls back to the proxy's IP (treating all clients as
  one), which is safe but overly restrictive.
- **WebSocket message limiting** prevents a single rogue client from flooding
  the event bus, protecting all other bucket clients.

## See also

- [ADR-0008](0008-single-api-key-auth.md) — single API key means no per-user
  limiting.
- [hsync_server/rate_limiter.py](https://github.com/albertobasso/hsync-server/blob/main/hsync_server/rate_limiter.py) —
  implementation.
