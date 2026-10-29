# ADR 0038 — Bootnode relays the full endpoint candidate list

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

`boot/1` discovery ([ADR-0032](0032-bootnode-discovery.md)) exists for peers that
are not on the same LAN: the client registers its data-plane listen endpoint(s),
the node relays a peer sample, and the requester dials an address to reach the
elected master. A peer's addresses are not interchangeable. The client knows
several for its data plane (`candidate_endpoints`: the observed STUN address, the
UPnP-mapped public endpoint, and the local address), and the externally observed
one is unreachable from inside the same NAT because most home routers do not
implement NAT loopback (hairpinning). A peer model built around a single relayed
address therefore cannot connect two peers that share a NAT — including two
clients on one host — even though a directly reachable LAN address exists. The
symptom is a repetitive `ConnectTimeoutError` on the slave while the master
serves normally on its LAN/loopback address.

This is the case WebRTC/ICE solves with a candidate set (host, server-reflexive,
relay) plus connectivity checks and priority ordering; the same idea is the
market norm (Syncthing discovers local + global and dials multiple addresses,
libp2p advertises multiaddrs, Tailscale falls back to a relay).

## Decision

We will relay the peer's **full candidate list** instead of a single endpoint:

1. `BootPeer` carries `endpoints: list[Endpoint]` (1–16, each `proto`/`host`/
   `port`) as its only endpoint representation: no separate single-address
   field. The node relays `register.endpoints[]` **verbatim and in order**; only
   a register that carried no endpoint at all (the first STUN register) falls
   back to a single-element list with the observed UDP source
   (`reachable=false`). Every implementation, fixture and mirror carries the
   same shape atomically, and the node never interprets or orders by it.
2. The requester keeps the whole list on the peer and **orders it host/LAN-first**
   at dial time (`dial_candidates`): loopback and same-subnet candidates (IPv4
   `/24`, IPv6 `/64`) before the externally advertised ones, which keep their
   advertised order. The advertised order is the peer's external-reachability
   preference; the requester's own-network priority is a client-side policy.
3. A peer that advertised several candidates is dialled by probing them in order
   with a **bounded per-candidate timeout** (a fingerprint-pinned TLS handshake,
   `MASTER_CANDIDATE_PROBE_TIMEOUT_S` = 3 s), and the first reachable one is used
   for the sync and WebSocket connection. A single-candidate peer (mDNS) skips
   the probe: its data-plane connection is its own reachability check, so the
   cost is unchanged. When no candidate is reachable the
   slave returns to the discovery loop instead of failing the run.
4. The candidate list is **advisory and unauthenticated**, exactly like the other
   relayed peer fields: the node never interprets or orders by it, and the data
   plane still authenticates identity by certificate pinning before any file is
   exchanged. Choosing the locally reachable candidate is a proximity preference,
   never proof of identity or authority.
5. The Android mirror (`BootPeer.endpoints`) and the byte-identical fixtures move
   with the contract; the drift/parity tests pin them.

Alternatives rejected: keeping the single `ip`/`port` and special-casing
same-public-IP peers at the node (the node would have to interpret
topology-dependent, unauthenticated data, and it cannot know the requester's LAN
address); running mDNS in parallel with the bootnode (a separate discovery-plane
change that does not fix an mDNS-blocked network and leaves stale public
endpoints unrecoverable).

## Consequences

- Two peers behind the same NAT — on one host or one LAN — connect over the local
  candidate instead of timing out on the hairpin-less public endpoint; a remote
  requester keeps the public candidate, and a stale public endpoint can now fall
  back to another candidate.
- Symmetric NAT with no UPnP and no routable candidate is not reachable through a
  direct candidate: the fix adds candidate fallback, and the
  [data plane relay](0047-p2p-relay-through-bootnode.md) covers the case where no
  candidate is dialable at all.
- The probe adds one short TLS handshake per candidate for multi-candidate peers,
  bounded by the 3 s per-candidate budget and skipped entirely for mDNS peers.
- Obligations: spec + fixtures + both `boot/1` implementations and the Kotlin
  mirror in one change; the client discovery mapping, the dial-time ordering and
  the slave connect path; regression tests for the relayed list, the ordering and
  the selection; and the `docs/`/`llm-wiki` updates in every affected repository.
