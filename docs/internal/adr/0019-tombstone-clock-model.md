# ADR 0019 — Tombstone clock model: why LWW-by-time is acceptable

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

The HSYNC conflict model uses two different resolution strategies for two
different primitives:

| Primitive | Resolution | Basis | ADR |
|-----------|-----------|-------|-----|
| File edits | Causal vector-clock merge | Content hash (SHA-256) + vector clocks, clock-independent | [ADR-0022](0022-causal-vector-clock-conflict-model.md) |
| Deletion markers | Last-Writer-Wins (LWW) | Deletion timestamp | [ADR-0003](0003-tombstone-gossip.md) |

[ADR-0022](0022-causal-vector-clock-conflict-model.md) explicitly rejects wall-clock
trust for content decisions: the content hash and the vector clock decide
direction, never the wall clock (which is informational only).

[ADR-0003](0003-tombstone-gossip.md) uses `merge()`/`record()` keeping the newest
`ts` for convergent tombstone state. This apparent contradiction deserves an
explicit justification.

## Decision

The LWW-by-time model for tombstones is accepted because the failure modes of
timestamp-based resolution are fundamentally less severe for deletions than for
content edits, and the existing guardrails bound the risk:

### 1. The TTL dominates the skew window

`TOMBSTONE_TTL_DAYS_DEFAULT` is 30 days. Typical clock skew between peers on
the same LAN or NTP-synced internet is seconds to minutes. A tombstone merge
that picks the "wrong" timestamp due to a 2-minute skew is indistinguishable
from a correct merge: the tombstone exists either way, and both peers converge
on the same LWW winner. The only practical difference is which peer's timestamp
is recorded — irrelevant for the binary "file is deleted" state.

### 2. Deletion is idempotent; edits are not

A wrong-direction edit merge silently overwrites user data. A wrong-timestamp
tombstone merge still results in a tombstone — the file stays deleted. The
failure mode of clock skew in ADR-0003 is a **metadata cosmetic** (the recorded
`ts` value), not data loss.

### 3. Edge case: prolonged partition (>30 days)

The only scenario where clock skew combined with tombstone LWW could cause data
resurrection:

- Peer A deletes file at `ts=1000`, peers B/C are offline.
- Peer B (clock reset to epoch, `ts=1`) also deletes the same file before
  reconnecting.
- Tombstones propagate, LWW picks `ts=1000` (A's), ignoring B's `ts=1`.
- The tombstone expires after 30 days (TTL).
- B's clock has since corrected; on the next sync B sees no tombstone and the
  file is absent locally → B re-uploads it.

This scenario requires: a clock reset on one peer **plus** a simultaneous
independent deletion on that peer **plus** a 30-day partition. This is
accepted as sufficiently improbable for HSYNC's target (single-user, small
fleet, rarely fully partitioned for weeks). The periodic resync and the
mass-deletion guard ([ADR-0015](0015-mass-deletion-guard.md)) provide
additional safety layers.

### 4. Alternatives rejected

| Alternative | Rejected because |
|-------------|-----------------|
| **Hash-based tombstone merge** (like ADR-0022) | Deletions have no content to hash; the only identity is the path. A path-based merge without timestamps degenerates to "delete always wins" — which is strictly more aggressive than LWW and would cause false deletions on partition heal. |
| **Vector clocks per tombstone** | Adds complexity disproportionate to the benefit: tombstones are binary markers with a 30-day TTL, not long-lived mutable state. |
| **Lamport timestamps** | Still wall-clock-dependent (logical clocks need initialisation); requires causal history tracking across the fleet. |

## Consequences

- The two-tier clock trust model is now explicit: **never trust clocks for
  content integrity** (ADR-0022), **accept clock skew as cosmetic for deletion
  metadata** (ADR-0003).
- The 30-day TTL is the primary defense against clock-skew-induced resurrection;
  reducing the TTL increases risk.
- If HSYNC ever scales to large fleets with frequent long partitions, the
  tombstone model should be revisited before any other component.

## See also

- [ADR-0003](0003-tombstone-gossip.md) — Tombstone gossip for deletions
- [ADR-0022](0022-causal-vector-clock-conflict-model.md) — Causal vector-clock conflict model
- [ADR-0015](0015-mass-deletion-guard.md) — Mass-deletion safety guard
