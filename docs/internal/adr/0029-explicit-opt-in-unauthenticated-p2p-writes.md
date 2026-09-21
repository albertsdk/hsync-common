# ADR 0029 — Explicit opt-in for unauthenticated p2p writes

- **Status:** Accepted
- **Date:** 2026-09-09

## Context

TLS with a self-signed certificate protects p2p traffic in transit, and TOFU
pins the endpoint after first use, but neither grants a peer permission to
mutate the master's bucket. ADR-0020 established the shared p2p key as write
authorization; the existing operational policy nevertheless allowed an
interactive client to write without a key. Interactivity is local process state,
not evidence the master can authenticate or authorize the remote peer, and it
does not provide a safe server-side default.

p2p peer-assisted download adds more read-only endpoints and makes the
read/write boundary more visible. No-key reads must continue to work on an
explicitly keyless trusted LAN, while mutation must fail closed unless both
sides deliberately enable the dangerous mode.

## Decision

We will use this LAN mutation policy:

1. When a p2p key is configured, every mutating request requires the matching
   Bearer key. The unauthenticated-write setting is ignored and cannot bypass a
   configured key.
2. When no p2p key is configured and `allow unauthenticated writes` is false
   (the default), read endpoints, health/time, source lookup, and read-only
   seeder downloads remain available, but mutation returns HTTP 403.
3. When no p2p key is configured and the master explicitly enables
   `allow unauthenticated writes`, mutation may proceed with the validated CID
   attribution supplied by the peer. This is authorization for a trusted LAN,
   not authentication of that CID.
4. A write-capable client must also enable its own local opt-in before emitting
   no-key mutations. A client opt-in cannot override a restrictive master.
5. Invocation interactivity is not part of authorization. The shared
   `p2p_write_requires_key` decision is true for a write direction unless the
   explicit opt-in is set.
6. Mutations include upload, delete, rename, permission update, delta apply, and
   tombstone mutation. Source lookup, inventory publication, file download,
   health, and time are read/control operations and do not become bucket writes.

The settings are explicit and disabled by default:
`P2P_ALLOW_UNAUTHENTICATED_WRITES` / `p2p_allow_unauthenticated_writes` on
Python and the corresponding persisted advanced setting on Android. Their UI
and CLI presentation must label the mode as dangerous.

This decision supersedes only the unauthenticated-write interpretation of
[ADR-0020](0020-p2p-security-model.md). ADR-0020's TLS, TOFU, LAN-key,
discovery-trust, and strict-pairing decisions remain accepted.

## Consequences

- A keyless installation is read-only by default, including interactive runs.
- Enabling no-key writes requires deliberate configuration on both the master
  and the writing client, reducing accidental exposure on guest/public LANs.
- The opt-in does not authenticate CID attribution and remains unsuitable for an
  untrusted network; operators needing authenticated writes must configure a LAN
  key.
- Every mutation endpoint must apply the same matrix. A permissive client never
  weakens a restrictive master, and a configured key always wins.
