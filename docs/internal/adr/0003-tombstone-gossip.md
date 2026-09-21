# ADR 0003 — Causal tombstone gossip for deletions

- **Status:** Accepted
- **Date:** 2026-06-21 (last revised 2026-08-13)

## Context

Deletion is asymmetric. When a file is removed on one node and a peer that was
**offline at deletion time** later runs a full reconciliation, it still has the
file locally and would treat it as "new", **resurrecting** the deleted file and
propagating it back to everyone. Reconciliation based only on the *present* set
of files cannot distinguish "never existed here" from "deleted while I was away".

Deletions follow the **same causal model as content edits** ([ADR-0022](0022-causal-vector-clock-conflict-model.md)):
the vector clock decides, never the wall clock. A deletion is an operation on
the path's causal history, exactly as an edit is — the tombstone inherits the
stored version clock for the path and is ticked by the deleter, so
delete-vs-recreate and delete-vs-delete resolve by causal dominance, immune to
clock skew.

## Decision

We record deletions as **causal tombstones** — explicit deletion markers — in a
shared `TombstoneStore` (`hsync_common.models.tombstone`) and propagate
(gossip) them between nodes so an absent file is recognised as *deleted* rather
than *missing*. Key properties:

- **Causal provenance per marker**: each entry carries the content hash of the
  deleted file (`sha256`), an opaque `version_id`, the author `origin_cid`, the
  informational `ts`, and the causal `vclock` — the stored version clock for the
  path merged and ticked by the deleter (`tick_vclock`, anti-aliasing invariant
  of ADR-0022).
- **Role-independent local recording**: every peer records its own deletion
  markers at deletion time — serving as p2p master or running as slave alike —
  so correctness never depends on which role observed the removal nor on the
  transport being up at that moment. A slave whose master is temporarily
  unreachable still records the marker; the next reconciliation then issues the
  `delete_remote` action, which speaks both transports' DELETE contracts (form
  fields against the central server, query parameters against the p2p master).
- **Causal merge for tombstones** (`merge()`): dominance decides — the marker
  with the dominant clock wins. Concurrent delete-delete merges to the
  componentwise clock maximum (`merge_vclocks`); true divergence is resolved by
  a deterministic content-based tie-break (content hash, then version id, then
  author cid). **The deletion timestamp never decides anything.**
- **Delete-vs-recreate is causal**: an edit concurrent with (not dominated by)
  a deletion resurrects the file — the re-created content's clock supersedes
  the tombstone, which is dropped. A tombstone causally **dominating** the
  local version is positive proof that the deletion descends from the common
  history: the client applies it unconditionally (the mass-deletion guard in
  [ADR-0015](0015-mass-deletion-guard.md) exempts these).
- **Privacy-preserving keys**: bucket-relative paths are SHA-256 hashed before
  storage.
- **Bounded growth**: `prune()` GCs markers older than
  `TOMBSTONE_TTL_DAYS_DEFAULT` (**90 days**). This is purely a **storage
  bound**: correctness never depends on it, because deletion decisions are
  causal. A peer offline beyond the window may still resurrect a file, which is
  why the mass-deletion guard remains the last line of defense.
- **Strict wire validation**: an entry without a structurally valid `vclock` is
  **not** a legal deletion marker and is dropped (never loaded with a
  fabricated empty clock). Counters must be non-negative ints (bool rejected),
  keys must be valid cids, clocks capped at `VCLOCK_MAX_ENTRIES` entries,
  timestamps within the anti-poisoning skew bound.
- **Persistence** in the installation ``syncstate.db`` (ADR-0025), with a
  wire shape (`to_payload()`) reused by the REST endpoints, the LAN gossip
  channel and the Android mirror (`Tombstones.kt`).

Tombstones are advertised as the `tombstones` capability
([ADR-0005](0005-protocol-versioning.md)).

## Consequences

- A file deleted anywhere stays deleted everywhere; offline peers no longer
  resurrect it on the next full sync — and the decision is now causal, so a
  clock-skewed peer cannot flip it.
- The wall clock is **informational only** for deletions, exactly as it is for
  content edits: one trust model, no exceptions.
- The TTL is a storage trade-off: a node offline **longer** than the retention
  window may miss a tombstone and resurrect a file — the periodic resync and
  the mass-deletion guard ([ADR-0015](0015-mass-deletion-guard.md)) bound this
  residual risk.
- Hashed keys mean the store never leaks the file tree, at the cost of not being
  human-readable for debugging.
- All consumers (server, client, Android) mirror the causal tombstone merge;
  cross-language parity is enforced by the `causal-tombstone-scenarios.json`
  golden fixture.

## See also

- [ADR-0022](0022-causal-vector-clock-conflict-model.md) — Causal vector-clock conflict model
- [ADR-0015](0015-mass-deletion-guard.md) — Mass-deletion safety guard
- [ADR-0007](0007-content-addressed-storage.md) — tombstone keys are also SHA-256 hashed
