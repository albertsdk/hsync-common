# ADR 0027 — LAN leadership lease: bounded incumbency and immediate yield

- **Status:** Accepted
- **Date:** 2026-09-04

## Context

The deterministic election ([ADR-0002](0002-lan-master-election.md)) converges
every peer on the same master from the same candidate view, and the periodic
staleness sweep bounds how long a hard-crashed master is kept (see
`lan-protocol.md`). One gap remained: when a serving master **loses** the
election (a `force_master` peer becomes `server_ready`, or the incumbent
restarts and re-joins), the client stopped its HTTP/WSS servers but **left its
incumbency advertised**: the local `server_ready` flag stayed set and the mDNS
TXT record still carried `server_ready=true`. The node therefore remained an
"incumbent" in its own view and in every peer's view even though it was no
longer serving — a *zombie incumbent* that can stall or skew subsequent
elections and, during a network partition, prolong a split-brain.

## Decision

Leadership is a **lease**: a node holds the right to serve only while it is the
elected master **and** is actually serving. The lease is renewed implicitly by
continuing to serve (the mDNS heartbeat keeps the incumbency fresh); a node
that stops being the elected master **yields immediately**:

1. it stops its HTTP and WebSocket servers,
2. it revokes its incumbency — clears the local `server_ready` flag *and*
   re-registers its mDNS record without `server_ready` (and without the
   `connected` presence count),
3. it logs a parsable `[MASTER YIELD]` marker (mirrored in Android).

The yield is driven by the existing discovery loop, which already re-checks
`is_master()` on every wake; the change is that the yield now also revokes
incumbency on the wire instead of only stopping the sockets.

## Consequences

- A node that yields is no longer an incumbent anywhere: peers re-run the
  deterministic election and converge on the correct master, closing the
  zombie-incumbent window.
- **No quorum is introduced.** A full network partition (two sides that cannot
  see each other) can still briefly yield two masters, exactly as before; this
  ADR does **not** claim at-most-one-master under partition. That guarantee
  would require a majority quorum with fixed membership, which conflicts with
  the dynamic home-LAN topology and would cost availability (a lone survivor
  could not serve). Divergence from such a partition is bounded by the causal
  vector-clock reconciliation ([ADR-0022](0022-causal-vector-clock-conflict-model.md))
  on heal.
- The `[MASTER YIELD]` label is part of the cross-language log contract: added
  to `ActionLabel` (SSOT) and mirrored in Android `LogAction` (parity-tested).
