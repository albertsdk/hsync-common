# ADR 0003 — Tombstone gossip for deletions

- **Status:** Accepted
- **Date:** 2026-06-22

## Context

Deletion is asymmetric. When a file is removed on one node and a peer that was
**offline at deletion time** later runs a full reconciliation, it still has the
file locally and would treat it as "new", **resurrecting** the deleted file and
propagating it back to everyone. Reconciliation based only on the *present* set
of files cannot distinguish "never existed here" from "deleted while I was away".

## Decision

We will record deletions as **tombstones** — explicit deletion markers — in a
shared `TombstoneStore` (`hsync_common.models.tombstone`) and propagate
(gossip) them between nodes so an absent file is recognised as *deleted* rather
than *missing*. Key properties:

- **Last-writer-wins merge** keyed by deletion timestamp (`merge()`/`record()`
  keep the newest `ts`), so server, LAN master and clients converge.
- **Privacy-preserving keys**: bucket-relative paths are SHA-256 hashed before
  storage.
- **Bounded growth**: `prune()` GCs markers older than
  `TOMBSTONE_TTL_DAYS_DEFAULT` (30 days).
- **Atomic persistence** to the `.hsynctombstones` side-car, with a wire shape
  (`to_payload()`) reused by the REST endpoints and the Android client.

Tombstones are advertised as the `tombstones` capability
([ADR-0005](0005-protocol-versioning.md)).

## Consequences

- A file deleted anywhere stays deleted everywhere; offline peers no longer
  resurrect it on the next full sync.
- The TTL is a deliberate trade-off: a node offline **longer** than the
  retention window may miss a tombstone and resurrect a file — acceptable for the
  target use, and tunable.
- Hashed keys mean the store never leaks the file tree, at the cost of not being
  human-readable for debugging.
- Tombstone LWW resolves *deletions* by time; concurrent *edits* are resolved by
  the separate, clock-independent conflict model
  ([ADR-0006](0006-master-authoritative-conflict-model.md)).
