# ADR 0035 — Rendezvous trust policy: SSH-like `ask` and `known_hosts`

> **Renamed since (2026-10-29, zero backward compatibility)**: the current
> names are `HSYNC_RENDEZVOUS_SERVER_TRUST` / `HSYNC_RENDEZVOUS_SERVER_TRUST_FILE`,
> `rendezvous_server_known_hosts.json`, `hsync trust rendezvous-server` and a pin
> per endpoint (`HSYNC_RENDEZVOUS_SERVER_FINGERPRINTS="host:port=fp[|fp]"`), so
> that several independent servers keep separate identities. The decision below
> is unchanged; only the vocabulary and the pin scope moved.

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

A self-hosted node is **self-signed by contract**, so on first contact the client
must either know the fingerprint out of band or be told to accept the node. Every
operator already knows the equivalent UX from OpenSSH: connect, be shown the
fingerprint, answer `yes`, and the decision is remembered in `known_hosts`.
`hsync p2p` provides the same, while keeping non-interactive runs deterministic.

Two constraints shape the design:

- **Determinism for automation.** A prompt must never silently accept on a
  service/`systemd`/container run with no terminal; those runs must stay
  fail-closed and explicit.
- **One decision, several front-ends.** The CLI prompts on a terminal, the
  desktop confirms with a dialog, Android will confirm in-app; all must share the
  same rule set so they cannot drift (the existing `PinDecision`/`pairing`
  precedent, ADR-0020/0034).

## Decision

1. **A single trust-policy SSOT** lives in
   `hsync_common/protocol/tls_trust.py`: `TrustPolicy`
   (`ask | accept_new | strict | none`, later extended with `chain` for the sync
   server — see ADR-0036) and the pure
   `evaluate_tls_trust(policy, stored, observed) -> TrustAction`
   (`proceed | pin_and_proceed | prompt | refuse`). `none` always proceeds; a
   changed or missing fingerprint is always refused.
2. **`ask` is the default.** An unknown node prompts and is pinned on
   acceptance; a known node is compared; a changed node is refused. In a
   non-interactive context (no terminal) `ask` does **not** prompt and fails
   closed, like SSH `BatchMode`. `accept_new` (silent first-sighting pin) and
   `strict` (explicit pin required) cover automation.
3. **The existing options keep their meaning as policy aliases:**
   `--rendezvous-tofu` = `accept-new`; `--rendezvous-fingerprint` (<=2) = `strict`;
   `--insecure` = `none`. New: `--rendezvous-trust {ask,accept-new,strict}` and
   `HSYNC_RENDEZVOUS_TRUST`. `ask` prompts **only on a terminal**; non-interactive
   acceptance is expressed with `accept-new`.
4. **The store is `rendezvous_known_hosts.json`**, managed like `known_hosts`:
   each `host:port` record carries `current`, `updated_at`, `first_seen` and
   `source` (`prompt | tofu | flag | cli`). The `0600`/`0700` JSON store and the
   `HSYNC_RENDEZVOUS_TRUST_FILE` override are unchanged.
5. **The user manages the store with `hsync trust rendezvous`**:
   `list`/`show`, `add HOST[:PORT] FINGERPRINT`, `remove HOST[:PORT]`
   (like `ssh-keygen -R`) and `fingerprint HOST[:PORT]` (read the node's
   fingerprint without trusting it, like `ssh-keyscan`).
6. **A refusal is fatal.** A user who declines the prompt, or a caller that
   cannot prompt, stops rendezvous and exits non-zero; the lease loop never
   re-prompts. A changed fingerprint is refused with the store path and the
   `trust remove` recovery command.

## Consequences

- The default first connection is interactive and SSH-like; subsequent runs are
  silent; automation uses `--rendezvous-tofu`/`--rendezvous-fingerprint` (or
  `--rendezvous-trust accept-new`).
- The desktop uses a pre-flight: it reads the fingerprint with
  `hsync trust rendezvous fingerprint`, shows a dialog, and starts the client with
  an explicit pin or `trust add`. Android mirrors `TrustPolicy` and persists to
  the same `rendezvous_known_hosts.json` name.
- New CLI/env surface obliges the man page, `docs/`, the WD OS5 packaging and
  the wiki to be updated atomically; the shared
  `p2p-rendezvous-trust-scenarios` fixture keeps the Python and Android decisions
  byte-for-byte equal.
