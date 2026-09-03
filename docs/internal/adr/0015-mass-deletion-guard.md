# ADR 0015 — Mass-Deletion Safety Guard

- **Status:** Accepted
- **Date:** 2026-10-15

## Context

In HSYNC,the server (or the elected LAN master) serves the file listing that
every connected peer reconciles its local state against on each sync cycle.
Files present locally but absent from the master listing are deleted to converge
toward the shared state.

This model is correct when the master listing is correct, but a transient
failure or misconfiguration can cause the master to expose an **empty or
nearly-empty bucket**. Examples of how this can happen:

- A LAN slave is mistakenly set to `--force-master` while its synced directory is
  empty (e.g. after a factory reset or a failed migration).
- The server's backing storage (S3/MinIO) is temporarily unavailable and returns
  an empty object list.
- A new bucket is created but a peer connects to it before the first file is
  uploaded — the master's empty listing would cause every local file to be
  deleted.
- A LAN master is elected whose network path is only partially accessible, and
  it times out the file-list request while returning an empty cache.

Without a safety mechanism, a single reconciliation cycle would **irreversibly
wipe every local file** on every connected peer — a mass data-loss event.

### Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| **Two-phase delete confirmation** (ask user each cycle) | Interrupts non-interactive daemon runs; impossible on embedded/NAS targets (WD OS5, systemd service) |
| **Trash/recycle-bin by default** | Adds storage complexity; doesn't solve the root cause (the master is wrong); trash must be cleaned eventually |
| **CRDT-based conflict resolution** | The conflict model is already causal (per-file vector clocks, ADR-0022) and deletions are already causal tombstones (ADR-0003); the guard addresses a different failure mode — a master exposing a wrong listing — which no conflict model can detect |
| **Per-file tombstone grace period** | Protects against spurious individual deletions but not a bulk wipe — 50 deleted files look the same as 1 deleted file to a tombstone check |
| **Threshold-based guard (chosen)** | A simple, configurable, zero-maintenance safety net that catches the bulk-wipe scenario before any data is touched |

## Decision

We will implement a **mass-deletion safety guard** on every client that pauses
the sync cycle when the number of files that would be deleted exceeds
configurable thresholds. The guard evaluates three conditions before any
deletion is executed:

1. **Empty master** — If the master exposes 0 files while the local peer has > 0
   files, the cycle is **always blocked**. An empty master is a suspect state,
   never a delete command. This check cannot be disabled by threshold tuning:
   the only way past it is to explicitly turn off the entire guard.

2. **Absolute threshold** — If the delete count reaches or surpasses
   `MASS_DELETE_THRESHOLD` (default 50), the cycle is blocked.

3. **Percentage threshold** — If the delete count reaches or surpasses
   `MASS_DELETE_PERCENT` (default 50) percent of the local file count, the cycle
   is blocked.

The guard only blocks **deletions** — uploads and downloads in the same cycle
proceed unaffected.

### Non-goals

- The guard does **not** validate individual delete decisions; a tombstone
  causally **dominating** the local version is positive proof the deletion
  descends from the common history and is applied unconditionally
  ([ADR-0003](0003-tombstone-gossip.md)).
- The guard does **not** recover deleted files — it prevents the deletion from
  happening in the first place. If a user or operator misconfigures a client
  (e.g. points it at a wrong, empty bucket and *disables* the guard), data can
  still be lost.
- The guard is not a substitute for backups or the `--ignore-delete` flag.

### Why block, not suspend?

A blocked cycle that skips deletions but still performs uploads and downloads
is a **safe partial sync** — changes in both directions propagate, but the
suspicious bulk deletion waits for the next cycle. If the master's listing
recovers in the meantime, the next cycle will see a normal (small) number of
deletions and proceed. If the master remains empty, the guard blocks again —
effectively an automatic circuit breaker.

## Consequences

### Benefits

- **Automatic protection** against the most dangerous failure mode in HSYNC —
  a wrong master listing — no operator awareness or special configuration
  required to benefit.
- **Graceful degradation** — when the guard trips, other sync operations
  continue. The peer is not cut off from the master.
- **Observable** — a `[GUARD]` log line and a structured `sync_paused` event
  are emitted each time the guard trips, making it detectable by monitoring
  and the desktop GUI.
- **Configurable** — thresholds can be raised, lowered, or disabled per
  deployment profile. A backup-oriented NAS can tighten thresholds while a
  developer's multi-machine workspace can relax them.

### Costs and limits

- **False positives are possible.** A legitimate bulk reorganisation (e.g.
  moving thousands of files to a new directory structure) will trip the guard.
  The operator must either temporarily disable the guard with
  `--no-mass-delete-guard` or raise the thresholds for that session.
- **Does not protect against slow, incremental data loss.** If an attacker or
  a buggy client deletes files at a rate of 10 per cycle, the guard will never
  trip. The tombstones ([ADR-0003](0003-tombstone-gossip.md)) and `--ignore-delete` flag are the defenses
  for that class of problem.
- **Adds a small constant-time overhead** per sync cycle: counting the delete
  actions against the thresholds. This is negligible compared to the I/O cost
  of the sync itself.

### Follow-up obligations

- The guard thresholds must be exposed in the CLI, configuration docs, man page,
  WD OS5 web UI, and the desktop GUI settings panel.
- The `[GUARD]` log label and `sync_paused` event must be documented in the
  log-legend and the structured-event reference so monitoring tools can detect
  the condition.

## References

- [ADR-0022](0022-causal-vector-clock-conflict-model.md) — Causal vector-clock conflict model
- [ADR-0003](0003-tombstone-gossip.md) — Causal tombstone gossip for deletions
- [ADR-0012](0012-rate-limiting.md) — Rate Limiting (similar threshold/bucket pattern)
- Implementation: `hsync_client.sync._mass_deletion_blocked()` in `hsync-client/hsync_client/sync.py`
