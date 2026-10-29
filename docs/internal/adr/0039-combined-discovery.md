# ADR 0039 — Combined mDNS and bootnode discovery

- **Status:** Accepted
- **Date:** 2026-10-01

## Context

A p2p group needs two discovery scopes at once: devices on the local network must
find each other with no external dependency, and devices on different networks
must find each other through the `boot/1` bootstrap node
([ADR-0032](0032-bootnode-discovery.md)). A client is frequently in both
situations at the same time — for example a laptop on the home LAN that also
needs to reach a peer elsewhere. Discovery was selected as one of two
**mutually exclusive** plans: with a bootnode configured the mDNS plan did not
run, so a node on the local network was invisible to a bootnode-configured peer
on the same network unless both were registered with the node and the NAT offered
a hairpin route, and every local sync paid a round trip through the bootnode.

The two sources already agree on the contract: mDNS TXT and the `boot/1`
`register` carry the same election advertisement (the same fields are relayed
verbatim by the node), and both are unauthenticated hints with the identity
established by certificate pinning. Nothing in the election or the data plane
requires the sources to be exclusive; only the plan selector did.

## Decision

We will run both sources together when a bootnode is configured, over **one
shared** peer state:

1. `build_discovery_plan` returns `MdnsDiscovery` when no bootnode is set, and a
   new `HybridDiscovery` (mDNS + `BootnodeDiscovery`) when one is — the single
   decision point, unchanged in shape for the sync core, which still sees only
   the `DiscoveryPlan` surface.
2. Both plans run over **one** `PeerManager`: `DiscoveryPlanState.create_peer_manager`
   is the single construction point, `start(peer_manager=...)` lets a plan adopt
   a shared instance, and the hybrid builds the manager once and injects it into
   both. A peer seen through both sources is one entry, so the election sees one
   candidate set and presence is never double-counted.
3. `wait_for_discovery` blocks on the shared condition once. The mDNS child owns
   the presence pair (extracted as `emit_discovery_status`), the bootnode child
   owns the discovery log, so the combined wait reports presence exactly once.
   A source that stops for good — the bootnode refusing trust — is disabled on
   its own ([ADR-0045](0045-discovery-source-degradation.md)): the remaining
   sources keep the group discoverable, so a failure in one source is never a
   failure of the plan.
4. `endpoint_published()` is the **AND** of the sources that can still carry
   traffic: with a bootnode the node is "ready" only once its endpoint is
   registered with the node (mDNS has no separate step), preserving the bounded
   readiness wait; a disabled source, which can never publish, is not waited on.
5. Merging a peer seen through both sources prefers the information each source
   actually has: the non-empty candidate list wins (`BootPeer.endpoints` is the
   full list; mDNS supplies one address), and `Peer.capabilities_known` stops the
   bootnode relay — which carries no capability flags — from clearing the TXT
   capabilities (`compression`, `delta`, `peer_download`) that mDNS advertised.
6. The `discovery` UI event reports `plan: "mdns+bootnode"` when a bootnode is
   configured (`"mdns"` otherwise) and the bootnode host; the field stays a flat
   optional string, so no events-schema bump.

Alternatives rejected: keeping the plans exclusive and documenting the limit
(the mixed-configuration case is a normal usage, not an error); relaying mDNS
through the bootnode (the node is a registry, not a relay).

## Consequences

- A bootnode-configured client is discoverable and discoverable-to both on the
  local network and across networks; a same-network peer is reached directly
  (and, behind the same NAT, over the local candidate per
  [ADR-0038](0038-bootnode-endpoint-candidate-list.md)) instead of by a hairpin
  route through the node.
- Presence is emitted once and the election is single, because peer state is
  shared rather than duplicated.
- The bootnode discovery cadence (spec `boot-1.md`: refresh every 30 s) is
  unchanged; mDNS adds only local broadcast, which does not consume the node's
  rate budget.
- Obligations: the single `PeerManager` construction and injection, the presence
  and readiness composition, the source-aware peer merge, the
  `discovery`-event value, the per-source failure isolation
  ([ADR-0045](0045-discovery-source-degradation.md)), and their tests and
  documentation.
- The local source is best-effort like any mDNS deployment: where mDNS is blocked
  (AP isolation) the local path is simply absent and the bootnode path carries
  the group, as before.
