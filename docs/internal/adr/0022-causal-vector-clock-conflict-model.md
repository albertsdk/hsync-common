# ADR 0022 — Causal vector-clock conflict model

- **Status:** Accepted
- **Date:** 2026-08-13

## Context

Concurrent edits from multiple writers must reconcile predictably without
trusting wall-clock timestamps (clock skew causes silent overwrites and false
conflicts) and without granting any single node authority over the others (a
role-based winner biases the cluster toward one node's edits regardless of
causality). A decentralized causal model based on vector clocks deduces the
history autonomously on every node: false conflicts vanish (dominance is
detected across relays), and no node is authoritative.

## Decision

### 1. Vector clock per file

Each recorded version (`FileVersion`) carries a `vclock: dict[str, int]` mapping
node cid → logical counter. Pure operations (`compare_vclocks`, `tick_vclock`,
`merge_vclocks`) live in `hsync_common.models.version` and are mirrored in
Kotlin (`util/Version.kt`).

### 2. Causal resolution matrix

`resolve_three_way(local_hash, local_vclock, remote_hash, remote_vclock,
base_hash)` decides by content identity first, then causal dominance, then a
deterministic tie-break — never by wall clock (see the source docstring for the
6-rule matrix).

### 3. Tie-break on true divergence (amended by ADR-0023)

When clocks are concurrent (true divergence), the version with the higher
**corrected modification time** (``corrected_mtime``, the local mtime shifted
by the clock offset measured against the server or a public SNTP host) wins.
When either side lacks the field or the two values tie, the deterministic
SHA-256 fallback picks the winner. The losing content is preserved as a
``_conflicted_copy_`` — the only case for conflict copies (extrema ratio).
Both sides compute the same winner from the same inputs.

> **Amended by [ADR-0023](0023-corrected-mtime-tie-break.md).**

### 4. No authoritative node

The server and the elected p2p master are **transport hubs only** (who serves,
ADR 0002); they do not decide conflicts by role. Every node applies the same
algorithm. Upload arbitration at the hub compares the incoming version against
its current stored version (causally, with a self-record pre-step for
out-of-band edits) and serializes concurrent uploads per path via the existing
`FileLockManager`.

### 5. Merge-on-record (convergence invariant)

The clock recorded after any sync is `merge_vclocks(local, remote)`. On a
conflict the winner's clock includes both histories, so third nodes recognise
either side as an ancestor and no false conflict propagates downstream.

### 6. Self-record-before-compare (anti-aliasing)

A node persists its own edit (tick + hash + version_id) when it observes it
(watcher for latency; reconcile/arbitration as catch-all). The advertised
version is always the store — two sequential local edits produce monotonically
increasing clocks, preventing aliasing (two distinct versions sharing one
clock ⇒ silent overwrite). The pure/persistent split keeps dry-run preview
read-only.

### 7. Capability, not version bump

A `Capability.vector_clocks` is advertised on the authenticated handshakes
(WS auth, p2p WSS) within the same protocol version (`api/1`, `ws/1`, `p2p/1`).
Version metadata is attached to file payloads (`FileDict.version`)
unconditionally by new builds; old peers ignore unknown fields. Absent metadata
⇒ empty clock, handled natively by the same matrix.

## Consequences

- Conflict copies appear only on true causal divergence.
- The raw wall clock is informational only (`ts`); causal decisions use hashes
  and vector clocks. The chronological tie-break uses only offset-corrected
  `corrected_mtime` values, never the raw clock (ADR-0023).
- Deletions follow the same causal model: tombstones carry vector clocks
  inherited from the deleted version and ticked by the deleter (ADR 0003).
- All consumers (server, client, Android) mirror the algorithm; cross-language
  parity is enforced by `causal-resolution-scenarios.json` golden fixtures.
