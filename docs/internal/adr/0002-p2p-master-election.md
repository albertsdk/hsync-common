# ADR 0002 — Deterministic p2p master election

- **Status:** Accepted
- **Date:** 2026-06-21

## Context

In p2p mode ([ADR-0001](0001-server-vs-p2p-modes.md)) there is no fixed
server, yet the bucket needs exactly **one node to host the transport hub** (the
HTTPS/WSS server peers connect to and that relays events). Two clients
implement the LAN: the Python client and the Android client. If they elected
masters by different rules they would split-brain — each believing a different
peer is master — corrupting the bucket. mDNS/TXT discovery is also
unauthenticated, so election input is a hint, never proof.

## Decision

We make master election a **deterministic, total-order function** defined once
in `hsync_common.protocol.p2p` (`elect_master`, `election_sort_key`) and mirrored
byte-for-byte by Android (`com.hsync.android.p2p.Election`). The winner is the
eligible candidate with the smallest sort key, prioritised:

1. `server_ready` (an already-serving incumbent — avoids needless takeover),
2. `force_master` (operator-pinned),
3. bidirectional `sync_direction` over upload/download-only,
4. earliest `startup_time`,
5. lowest `cid` lexicographically (final deterministic tiebreaker).

`never_master` nodes are excluded; if no candidate is eligible, **no master is
elected** (`NO_MASTER`) rather than a wrong one. Parity is enforced by golden
fixtures (`protocol/fixtures/p2p-election-scenarios.json`) replayed in both
`tests/test_protocol_p2p.py` and Android `P2PElectionParityTest`.

## Consequences

- Identical inputs yield an identical master on every peer and language → no
  split-brain by construction; divergence fails a parity test, not the field.
- The algorithm is pure and clock-light: it depends only on advertised TXT
  fields, so it is testable offline and immune to per-node clock skew beyond the
  `startup_time` tiebreaker.
- Edge cases are first-class and observable via parsable log markers
  (`[MASTER CONFLICT]`, `[MASTER TAKEOVER]`, `[NO MASTER]`) and structured events.
- The election decides only *who serves* the transport hub; it confers no
  authority over conflicts, which are resolved causally on every node
  ([ADR-0022](0022-causal-vector-clock-conflict-model.md)). *Who to trust* is a
  separate concern (TOFU pinning / pairing) documented in
  [p2p-protocol.md](../../p2p-protocol.md).
- Any change to ranking or TXT keys must regenerate the golden fixtures and the
  Android copy, keeping the human doc and the machine sources aligned.
