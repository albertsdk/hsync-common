# ADR 0021 — Server-side conflicted copy on concurrent upload

- **Status:** Accepted
- **Date:** 2026-08-13

## Context

When two clients upload different content for the same file path, the server
(`hsync_server/api/files/upload.py`) arbitrates causally against its stored
version ([ADR-0022](0022-causal-vector-clock-conflict-model.md)). On a true
divergence (concurrent vector clocks) a deterministic tie-break picks the winner
for the canonical path. The losing content must survive as a traceable copy so
no user-written data is silently lost.

## Decision

The receiver (server or p2p master) preserves the losing content as a
**server-side conflicted copy** whenever an upload loses a tie-break:

- The losing bytes are renamed to:
  ```
  <filename>_conflicted_copy_<ISO8601>_<cid>.<ext>
  ```
  where `<cid>` is the author of the losing content (the uploader when the
  incoming upload loses; the stored `origin_cid`, falling back to the uploader,
  when the server's current content loses).
- The new (winning) content is written atomically to the original path.
- On the wire, the upload response carries an explicit outcome:
  - `201` with `resolution: "accepted" | "accepted_conflict_won"` on success;
  - `409 superseded` when the upload is causally dominated (stale — an ancestor
    version, nothing lost, no copy);
  - `409 conflict_lost` when the upload loses a tie-break (its bytes are
    preserved as the conflicted copy; the client downloads the winner).
- The delta apply endpoint (`api/files/delta/apply.py`) uses the same contract.

## Consequences

- Conflicted copies appear only on true causal divergence; stale uploads produce
  no copy (the ancestor's data is fully contained in the winner's history).
- The conflicted copy is a regular new file: it appears in the bucket listing
  and syncs to all peers on their next reconciliation — every peer sees both
  versions.
- Conflicted copies accumulate over time; cleanup is manual (the user deletes
  the copy once resolved), the same as Dropbox and Syncthing.
- Arbitration runs inside the existing per-path `FileLockManager`, so two
  concurrent uploads for the same path are serialized: the second sees the
  version registered by the first.

## Related

- [ADR-0022](0022-causal-vector-clock-conflict-model.md) — Causal conflict model
- `hsync_server/api/files/upload.py` — Upload arbitration + conflicted copy
- `hsync_server/api/files/delta/apply.py` — Delta-apply arbitration (same contract)
