# ADR 0027 — p2p leadership lease: bounded incumbency and immediate yield

- **Status:** Accepted
- **Date:** 2026-09-04

## Context

The deterministic election ([ADR-0002](0002-p2p-master-election.md)) converges
every peer on the same master from the same candidate view, and the periodic
staleness sweep bounds how long a hard-crashed master is kept (see
`p2p-protocol.md`). A serving master can still **lose** the election: that
happens when another peer has also become `server_ready` — which, because
exactly one node serves per healthy partition, occurs on **network-partition
heal**, when the two sides elected different masters and, on convergence, the
deterministic election picks one (a `force_master` peer wins at parity) and the
other yields.

If a losing master only stopped its HTTP/WSS servers while still advertising
`server_ready=true` (local flag and mDNS TXT record), it would remain an
"incumbent" in its own view and in every peer's view although it is no longer
serving — a *zombie incumbent* that can stall or skew subsequent elections.
Incumbency must therefore be revoked on the wire, not just locally.

## Decision

Leadership is a **lease**: a node holds the right to serve only while it is the
elected master **and** is actually serving. The lease is renewed implicitly by
continuing to serve (the mDNS heartbeat keeps the incumbency fresh); a node
that stops being the elected master **yields immediately**:

1. it closes the control plane's publish gate (bumping a publish epoch) and then
   stops serving on its single HTTPS/WSS listener (live WebSocket clients are
   closed and new requests are refused), so no event can be pushed during the
   yield window and a handshake still in flight is not admitted — both observe
   the publish epoch,
2. it revokes its incumbency — clears the local `server_ready` flag *and*
   re-registers its mDNS record without `server_ready` (and without the
   `connected` presence count),
3. it logs a parsable `[MASTER YIELD]` marker (mirrored in Android).

The yield is driven by the discovery loop, which re-checks `is_master()` on
every wake and revokes incumbency on the wire when the node stops being the
elected master.

## Consequences

- A node that yields is no longer an incumbent anywhere: peers re-run the
  deterministic election and converge on the correct master, closing the
  zombie-incumbent window.
- **No quorum is introduced.** A full network partition (two sides that cannot
  see each other) can briefly yield two masters; this ADR does **not** claim
  at-most-one-master under partition. That guarantee would require a majority
  quorum with fixed membership, which conflicts with the dynamic home-LAN
  topology and would cost availability (a lone survivor could not serve).
  Divergence from such a partition is bounded by the causal vector-clock
  reconciliation ([ADR-0022](0022-causal-vector-clock-conflict-model.md)) on
  heal.
- The `[MASTER YIELD]` label is part of the cross-language log contract: it
  lives in `ActionLabel` (SSOT) and is mirrored in the Android `LogAction`
  (parity-tested).
