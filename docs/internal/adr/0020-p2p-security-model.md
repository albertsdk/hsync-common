# ADR 0020 — p2p security model: TOFU pinning, p2p key, and strict pairing

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

p2p mode ([ADR-0001](0001-server-vs-p2p-modes.md)) operates without a
central authentication authority. Peers discover each other over unauthenticated
mDNS and communicate over HTTPS/WSS on a local network. The security model must
address:

- **Peer identity**: how does a slave know it is talking to the real master and
  not a rogue device on the same network?
- **Write authorization**: which peers are allowed to push file changes to the
  master?
- **Rendezvous trust**: mDNS/TXT records are unauthenticated — what can an
  attacker spoof?

These decisions are specified technically in
[`docs/p2p-protocol.md`](../../p2p-protocol.md); this ADR records them as
architectural decisions with explicit trade-offs and accepted risks.

## Decision

The p2p security model rests on three pillars, each addressing a specific
trust boundary:

### 1. TOFU (Trust-On-First-Use) certificate pinning

**Decision**: each peer, on first connection to a master, records the master's
TLS certificate fingerprint (`cert_fp`). On subsequent connections, the
fingerprint MUST match; a change is rejected as a potential MITM.

- Implementation: `hsync_client/pinning.py` (Python), `PinStore.kt` (Android).
- The master's self-signed certificate is persisted (`ssl_utils.py`) so the
  fingerprint is stable across restarts.
- A fingerprint mismatch produces a `SecurityEvent.FingerprintChanged` and
  blocks the connection, requiring operator intervention to clear the pin.

**Rationale**: TOFU is the standard trust rendezvousping model for
decentralized systems (SSH, Syncthing). It provides strong protection against
active MITM after the first connection, at the cost of a vulnerable first
connection window. In a home LAN, the first-connection window is small and
the attacker must be physically present on the network during setup.

**Accepted risk**: an attacker present during the very first pairing can
impersonate the master permanently. Mitigation: strict pairing mode (see §3)
eliminates even this window.

### 2. p2p key write authorization

**Decision**: a shared secret (p2p key, distinct from the server's per-account
tokens) gates write access in p2p mode. Peers that know the key can push
changes; peers without it are read-only observers.

- The key is set via `HSYNC_P2P_KEY` or `--p2p-key-fd`.
- Write policy is enforced by `_check_p2p_write_policy` in the master.
- A keyless peer can mutate only with an explicit dangerous opt-in on **both**
  the writing client and the master ([ADR-0029](0029-explicit-opt-in-unauthenticated-p2p-writes.md));
  interactivity is never an authorization exception.
- The p2p key is **never used for encryption** (TLS handles that); it is purely
  an authorization token.

**Rationale**: the p2p key prevents casual neighbors or guest devices on the
same Wi-Fi from injecting files. It is not a cryptographic identity — TOFU
pinning serves that role — but a coarse "are you part of my sync group?" gate.

**Accepted risk**: the p2p key is a shared secret; compromise of one device
compromises the whole p2p group. This is a deliberate contrast with the server's
per-account token model ([ADR-0008](0008-client-accounts.md)), where each device
has its own revocable key; the p2p group remains a single shared trust domain
(single-user/small-family fleet).

### 3. Strict pairing mode (optional)

**Decision**: the p2p master follows the same `TrustPolicy` as the other
self-signed transports ([ADR-0040](0040-p2p-master-trust-policy.md)): `ask`
(the default) confirms a first-seen fingerprint on a terminal and fails closed
without one, `accept-new` pins it silently, and `strict` requires an explicit
out-of-band pin before the first connection.

- Implementation: `protocol/tls_trust.py` + `protocol/pairing.py` (Python),
  `p2p/Pairing.kt` (Android).
- `strict` is the escalation for deployments whose network cannot be trusted
during setup.
- A `SecurityEvent.PairingNeeded` is emitted when a new peer attempts to
  connect and strict pairing is active.

**Rationale**: eliminates the TOFU first-connection vulnerability entirely.
Suitable for networks where the operator cannot trust the LAN during setup
(e.g. shared office Wi-Fi).

### 4. mDNS/TXT record trust

**Decision**: mDNS/TXT records are treated as **rendezvous hints, never as
proof of identity**. The election algorithm ([ADR-0002](0002-p2p-master-election.md))
uses TXT fields as inputs to a deterministic ranking, but the trust decision
(after election) is entirely separate: TOFU pinning + p2p key.

A peer with a `cert_fp` in its TXT record that does not match the pinned
fingerprint is discarded at rendezvous time (`P2PPeer.fromNsdServiceInfo`).

**Rationale**: mDNS is unauthenticated by design. Any device on the LAN can
spoof a TXT record. The security model treats the rendezvous layer as an
untrusted bulletin board and moves all trust decisions to the TLS+key layer.

## Consequences

- **Three-tier trust escalation**: TOFU (default, convenience) → TOFU + p2p key
  (default with write access) → Strict pairing (maximum security).
- **No CA dependency**: self-signed certificates with TOFU avoid the operational
  burden of a private CA, while providing equivalent MITM protection after first
  contact.
- **Rendezvous is untrusted by design**: eliminating trust from mDNS simplifies
  the threat model — no need to secure a protocol that is inherently unsecurable.
- **Shared secret model**: the p2p key is a shared secret; the server's account
  tokens ([ADR-0008](0008-client-accounts.md)) are per-account and individually
  revocable. Revoking the p2p key requires rotating it and updating all peers
  simultaneously.

## See also

- [ADR-0001](0001-server-vs-p2p-modes.md) — p2p mode overview
- [ADR-0002](0002-p2p-master-election.md) — Deterministic master election
- [ADR-0008](0008-client-accounts.md) — Server-side account token model
- [ADR-0029](0029-explicit-opt-in-unauthenticated-p2p-writes.md) — Explicit opt-in for unauthenticated p2p writes
- [`docs/p2p-protocol.md`](../../p2p-protocol.md) — Full p2p protocol specification
- Implementation: `hsync_client/pinning.py`, `protocol/pairing.py`, `ssl_utils.py`
