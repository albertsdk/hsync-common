# ADR 0045 — A rendezvous source failure degrades rendezvous, it never fails the run

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

Peer rendezvous runs two independent sources over one shared peer state
([ADR-0039](0039-combined-rendezvous.md)): mDNS on the local network, always
active, and the `rdv/1` rendezvous channel for cross-network rendezvous, present
only when a rendezvous is configured. Both produce unauthenticated *hints*: the
identity of a peer is established by certificate pinning on the data plane
([ADR-0040](0040-p2p-master-trust-policy.md)), never by the rendezvous layer.

The sources were treated as one unit when they failed. A rendezvous that answered
with an untrusted certificate stopped its lease loop and ended the whole p2p run
with the fatal exit code, even when the local network had live peers; and the
desktop's start pre-flight probed an unpinned rendezvous and abandoned every run
when the probe could not read a fingerprint — so a device with a stale rendezvous
server never synced at all, on any network, with no indication that the local
network would have worked.

That coupling contradicts what the rendezvous is: an *optional* helper for devices
that cannot see each other locally. Its unavailability (a node that is down, or
one whose identity cannot be confirmed) says nothing about the local network,
which keeps working and keeps authenticating its peers on its own.

## Decision

1. A rendezvous source that stops delivering peers is **disabled on its own**.
   The rendezvous source stops its lease loop when the node is untrusted
   (policy `ask` without a terminal, `strict` without a pin, a changed pin) and
   reports a structured warning (`source: "rendezvous"`, `reason: "untrusted"`);
   it never contacts that node again, not even for the departure frame. The
   remaining sources keep feeding the shared peer state and the sync proceeds.
2. There is **no fatal rendezvous error**. The plan surface cannot fail the run
   for a source, so the sync core has no fatal branch to classify: it waits,
   elects and syncs as long as *some* source can deliver peers, and a
   single-source deployment (mDNS only) is unchanged.
3. An unreachable node is not a stopped source: the lease loop keeps retrying at
   the `rdv/1` cadence and reports the transient warning it already reported.
   Only a trust refusal is permanent for the process lifetime.
4. **Readiness follows the sources that can still carry traffic**: an endpoint
   publication from a disabled source is no longer required, because it can
   never arrive — a source that carries no traffic must not delay mastership.
5. The **desktop pre-flight** degrades with the same rule: a rendezvous whose
   fingerprint cannot be read produces a warning and the run continues on the
   local network, while an unreachable (or refused) *sync server* still cancels
   the start, because server mode has no alternative transport.
6. Pinning remains the remediation path: the client keeps emitting
   `pairing_needed`/`fingerprint_changed` with `scope: "rendezvous"`, and the
   desktop pins on confirmation and offers to restart the run.

Alternatives rejected: keeping the fatal abort and documenting the
workaround (an optional source must not decide whether a device syncs at all);
silently continuing with no signal (the operator could not tell why cross-network
peers stopped appearing); contacting the untrusted node again to test it (the
`bucket_token` would leak to an attacker).

## Consequences

- A device with an unreachable or unpinned discovery servers syncs on its local
  network from the first run, and joins the group across networks once the node
  is reachable and trusted.
- Degrading never weakens authentication: a refused node is never contacted, and
  every peer is still pinned on the data plane.
- The failure is observable on the structured channel and in the log (source +
  reason), so a front-end can surface it without scraping prose.
- Obligations: the per-source disabled state and its warning
  (`p2p_rendezvous_rdv.py`), the readiness composition
  (`p2p_rendezvous_hybrid.py`), the removal of the fatal rendezvous branch from
  `p2p_handler.run_p2p_mode`, the desktop pre-flight rule
  (`main_window/trust.py`), and their tests and user documentation.
