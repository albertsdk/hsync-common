# ADR 0006 — Master-authoritative conflict model

- **Status:** Superseded by [ADR-0022](0022-causal-vector-clock-conflict-model.md)
- **Date:** 2025-11-12
- **Superseded:** 2026-08-13

## Context

In server mode and LAN P2P mode, every peer synchronizes through a single
hub: the central server, or the elected LAN master. When two writers changed
the same file, the simplest reconciliation rule was to treat the hub's copy as
authoritative: whichever version the hub held won, and the other side was
preserved as a conflict copy (or overwritten).

## Decision

The hub (server or elected LAN master) was **authoritative by role**: its copy
won every content conflict, and the losing side was renamed to a conflict copy
for traceability.

## Consequences

- Conflict resolution was trivial to implement and reason about.
- However, node identity (not content or causality) decided what a user kept:
  edits made on a device that lost the race to the hub could be demoted even
  when they were chronologically and causally later.
- Clock-skew handling leaned on wall-clock (mtime) comparisons with tolerance
  windows, which produced false conflicts and misleading directions.

ADR-0022 replaced this model with a decentralized causal one: vector clocks
resolve dominance, a deterministic SHA-256 tie-break decides true divergence,
and the hub is a transport-only coordinator. Conflict copies survive only as
the preservation mechanism for the content that loses a genuine tie-break.
