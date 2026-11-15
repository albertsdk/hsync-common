# ADR 0051 — Automatic TLS trust policy (`auto`)

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

Three transports authenticate a certificate with the shared `TrustPolicy`
(ADR-0035, ADR-0036, ADR-0040): the rendezvous node and the P2P master are
self-signed by contract, while the sync server is either self-signed or fronted
by a reverse proxy with a public CA. A user running the Desktop had to know which
case applied to their server and pick `chain`, `ask`, `accept-new`, `strict` or
`none` accordingly; the three identity-check controls also worded the same policy
differently, which made equivalent options look distinct.

## Decision

Add one **meta-policy**, `auto`, resolved to a concrete policy before the pure
rule runs:

- `resolve_auto_policy(policy, stored_fp, *, chain_trusted)`
  (`hsync_common/protocol/tls_trust.py`) returns the policy unchanged unless it
  is `auto`, and for `auto` selects, in order:
  1. a stored pin (even a malformed one) → `strict`, so a known identity is
     enforced and a change is refused;
  2. `chain_trusted` → `chain` (standard CA validation, no pin);
  3. otherwise → `accept-new` (pin the first sighting).
- `evaluate_tls_trust` refuses an unresolved `auto`: it has no
  `chain_trusted` input, so callers must resolve first (fail closed).
- The sync server computes `chain_trusted` with a **verified** TLS handshake
  against the system CA or `--ca-cert`, using the same SNI/hostname as the real
  request. A verified handshake also supplies the fingerprint; only when it fails
  verification is a separate unverified handshake used for the TOFU pin. The
  self-signed transports pass `chain_trusted=False`.
- A **changed** fingerprint is refused under every resolved policy and is never
  replaced silently.
- A first-sighting TOFU acceptance (`auto` or `accept-new`) keeps the durable pin
  and emits a non-blocking notice with the fingerprint; no prompt is required.
- The Desktop makes `auto` the default for its three identity checks and passes
  the value explicitly; the CLI defaults stay conservative (`chain` for the
  server, `ask` for self-signed). The Desktop menus expose four values (three for
  the P2P master): `auto`, `ask`, `strict`, `none`; `chain` and `accept-new`
  remain CLI-only.
- Front-ends normalize a stored `chain`/`accept-new` to `auto` on read; `ask`,
  `strict` and `none` round-trip unchanged.

## Consequences

- **No prompt by default**: a CA-valid server is validated, and a self-signed
  endpoint is pinned on first use with a visible, auditable notice.
- **The first connection is still trusted** (TOFU) when neither a pin nor a CA
  chain is available. This is the deliberate cost of "automatic"; the trust list
  remains the place to verify and re-pin, and a later change is always refused.
- **Migration is a relaxation** for an install that explicitly chose
  `chain`/`accept-new`: both become `auto`, so `chain` also TOFUs a self-signed
  server. `strict`/`none` stay explicit and are never rewritten.
- The shared `p2p-rendezvous-trust-scenarios` fixture gains `auto` rows (resolved
  with `chain_trusted=False`), and the Kotlin mirror resolves `auto` the same way.
- ADR-0035/0036/0040 remain the rules for the concrete policies; `auto` only
  chooses among them.
