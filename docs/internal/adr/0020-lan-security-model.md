# ADR 0020 — LAN security model: TOFU pinning, LAN key, and strict pairing

- **Status:** Accepted; unauthenticated-write policy superseded by [ADR-0029](0029-explicit-opt-in-unauthenticated-lan-writes.md)
- **Date:** 2026-10-15

## Context

LAN P2P mode ([ADR-0001](0001-server-vs-lan-modes.md)) operates without a
central authentication authority. Peers discover each other over unauthenticated
mDNS and communicate over HTTPS/WSS on a local network. The security model must
address:

- **Peer identity**: how does a slave know it is talking to the real master and
  not a rogue device on the same network?
- **Write authorization**: which peers are allowed to push file changes to the
  master?
- **Discovery trust**: mDNS/TXT records are unauthenticated — what can an
  attacker spoof?

These decisions were previously documented only in
[`docs/lan-protocol.md`](../../lan-protocol.md) as a technical specification.
This ADR formalizes them as architectural decisions with explicit trade-offs
and accepted risks.

## Decision

The LAN security model rests on three pillars, each addressing a specific
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

**Rationale**: TOFU is the standard trust bootstrapping model for
decentralized systems (SSH, Syncthing). It provides strong protection against
active MITM after the first connection, at the cost of a vulnerable first
connection window. In a home LAN, the first-connection window is small and
the attacker must be physically present on the network during setup.

**Accepted risk**: an attacker present during the very first pairing can
impersonate the master permanently. Mitigation: strict pairing mode (see §3)
eliminates even this window.

### 2. LAN key write authorization

> **Superseded in part by [ADR-0029](0029-explicit-opt-in-unauthenticated-lan-writes.md).**
> Keyless peers remain read-only by default, but mutation may be enabled only by
> an explicit dangerous opt-in on both the writing client and the master.
> Interactivity is no longer an authorization exception.

**Decision**: a shared secret (LAN key, distinct from the server's per-account
tokens) gates write access in LAN mode. Peers that know the key can push
changes; peers without it are read-only observers.

- The key is set via `HSYNC_LAN_KEY` or `--lan-key-fd`.
- Write policy is enforced by `_check_lan_write_policy` in the master.
- The LAN key is **never used for encryption** (TLS handles that); it is purely
  an authorization token.

**Rationale**: the LAN key prevents casual neighbors or guest devices on the
same Wi-Fi from injecting files. It is not a cryptographic identity — TOFU
pinning serves that role — but a coarse "are you part of my sync group?" gate.

**Accepted risk**: the LAN key is a shared secret; compromise of one device
compromises the whole LAN group. This is a deliberate contrast with the server's
per-account token model ([ADR-0008](0008-client-accounts.md)), where each device
has its own revocable key; the LAN group remains a single shared trust domain
(single-user/small-family fleet).

### 3. Strict pairing mode (optional)

**Decision**: when `--lan-require-pairing` is set, TOFU is bypassed and a
manual out-of-band confirmation is required before the first connection. The
master displays a pairing code; the slave operator must confirm it.

- Implementation: `protocol/pairing.py` (Python), `Pairing.kt` (Android).
- Pairing is an optional escalation for security-sensitive deployments.
- A `SecurityEvent.PairingNeeded` is emitted when a new peer attempts to
  connect and strict pairing is active.

**Rationale**: eliminates the TOFU first-connection vulnerability entirely.
Suitable for networks where the operator cannot trust the LAN during setup
(e.g. shared office Wi-Fi).

### 4. mDNS/TXT record trust

**Decision**: mDNS/TXT records are treated as **discovery hints, never as
proof of identity**. The election algorithm ([ADR-0002](0002-lan-master-election.md))
uses TXT fields as inputs to a deterministic ranking, but the trust decision
(after election) is entirely separate: TOFU pinning + LAN key.

A peer with a `cert_fp` in its TXT record that does not match the pinned
fingerprint is discarded at discovery time (`LanPeer.fromNsdServiceInfo`).

**Rationale**: mDNS is unauthenticated by design. Any device on the LAN can
spoof a TXT record. The security model treats the discovery layer as an
untrusted bulletin board and moves all trust decisions to the TLS+key layer.

## Consequences

- **Three-tier trust escalation**: TOFU (default, convenience) → TOFU + LAN key
  (default with write access) → Strict pairing (maximum security).
- **No CA dependency**: self-signed certificates with TOFU avoid the operational
  burden of a private CA, while providing equivalent MITM protection after first
  contact.
- **Discovery is untrusted by design**: eliminating trust from mDNS simplifies
  the threat model — no need to secure a protocol that is inherently unsecurable.
- **Shared secret model**: the LAN key is a shared secret; the server's account
  tokens ([ADR-0008](0008-client-accounts.md)) are per-account and individually
  revocable. Revoking the LAN key requires rotating it and updating all peers
  simultaneously.

## See also

- [ADR-0001](0001-server-vs-lan-modes.md) — LAN P2P mode overview
- [ADR-0002](0002-lan-master-election.md) — Deterministic master election
- [ADR-0008](0008-client-accounts.md) — Server-side account token model
- [ADR-0029](0029-explicit-opt-in-unauthenticated-lan-writes.md) — Explicit opt-in for unauthenticated LAN writes (supersedes only that policy)
- [`docs/lan-protocol.md`](../../lan-protocol.md) — Full LAN protocol specification
- Implementation: `hsync_client/pinning.py`, `protocol/pairing.py`, `ssl_utils.py`
