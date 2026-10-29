# ADR 0047 — Data plane relay through the rendezvous

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

`rdv/1` rendezvous ([ADR-0032](0032-rendezvous-rendezvous.md)) plus the candidate
list ([ADR-0038](0038-rendezvous-endpoint-candidate-list.md)) gets two peers
together **as long as one of them accepts an inbound TCP connection**. Behind
carrier-grade NAT — a phone hotspot, a router with a data SIM — neither peer has
a dialable endpoint: the carrier's NAT holds the only public address, forwards
nothing, and UPnP can only configure the subscriber's own router, not the
carrier's. The group discovers itself, elects a master, publishes its endpoints,
and then never connects. The documented outcome was "unreachable, by design".

That leaves a whole class of real deployments without sync: two home users on
mobile links, a laptop tethered to a phone, a remote site on LTE. TCP hole
punching does not solve it (symmetric NAT, and it would require simultaneous
open), and moving the data plane to UDP/QUIC to make UDP hole punching possible
means rewriting `p2p/1`. The one element that is always publicly reachable — and
already authenticated, authorized and rate-limited — is the rendezvous.

## Decision

The rendezvous can relay the data plane, **opt-in per node** (`--relay`), carrying
the peers' TLS **verbatim**:

1. Four new `rdv/1` frames (`relay_listen`, `relay_ping`, `relay_connect`,
   `relay_attach`) plus their replies (`relay_listening`, `relay_incoming`,
   `relay_ok`, `relay_error`), added to the same protocol version. The listener
   (master) holds a control stream; a requester pairs with `relay_connect`; the
   listener attaches one fresh stream per announced session; the node bridges the
   two streams with a fixed 64 KiB buffer and `drain()` on both sides.
2. **Opaque relay.** The node never terminates or inspects the TLS: content,
   names and credentials stay invisible, and the peers keep authenticating each
   other by certificate pinning. The node does observe the pairing
   (`cid` ↔ `cid`) and the byte volume, which the operator documentation states
   plainly.
3. **Last resort on the client.** Direct candidates keep priority in the shared
   host/LAN-first order; the relay is opened only when every candidate failed.
   The requester dials a loopback endpoint bridged to the relayed stream, and the
   master bridges relayed sessions to its own `listen_port`, so neither the
   transfer core nor the UI learns that the path is relayed (the displayed master
   address stays the real one).
4. **Ownership and authorization reuse.** `relay_listen` is accepted only from the
   current owner of the `(cid, bucket, group)` record; `relay_attach` must match
   `relay_id`, listener `cid`/`bucket` and the listener's source IP; every relay
   frame carries the optional `bucket_token`, so a protected/private node refuses
   uniformly (`token_required`).
5. **Bounded by construction.** Session ceilings are host-derived (globally, per
   source IP and per bucket), the aggregate byte rate and the per-session byte
   ceiling are operator flags, an unattached session expires, an idle session is
   closed, and the relay keeps aggregate counters only (the no-log invariant is
   unchanged: nothing peer-identifying reaches disk).

## Consequences

- Two peers that no inbound NAT mapping reaches sync through the node, at the cost
  of two network legs and the node's uplink — which is why the node opts in and
  why the byte rate is capped by default.
- The node is no longer purely a rendezvous point. Its threat model grows by a
  bandwidth/DoS surface, answered with opt-in plus quotas, and by the metadata it
  necessarily sees (pairing, volume), answered with documentation and with
  keeping the payload opaque.
- A group whose **master** is relayable-only still serves every slave through one
  hop; peer-assisted download keeps using direct seeder endpoints and falls back
  to the master, so no file transfer depends on the relay being extended to
  seeders.
- Obligations: spec + fixtures + the daemon and the mirrored validators in one
  change, the client's `RelayDialer`/`RelayAcceptor`, the `[RELAY]` log label, the
  quotas and metrics, and the `docs/`/`llm-wiki` updates in every affected
  repository. The future C port implements the same frames.
