# ADR 0006 — Master-authoritative conflict model

- **Status:** Accepted
- **Date:** 2026-06-21

## Context

Concurrent edits from multiple writers must reconcile predictably. A pure
mtime + content-hash heuristic mis-resolves under skewed clocks, concurrent
renames or long offline periods, and can overwrite a local edit silently. A full
CRDT/version-vector engine would solve ordering but adds large complexity that
HSYNC's use (a small number of trusted peers with one authoritative node) does
not justify.

## Decision

We will adopt an explicit **master-authoritative, non-CRDT** model with a
clock-independent three-way merge, centralised in
`hsync_common.models.version`:

- Each peer remembers, per path, the content hash it last agreed on with the
  authoritative node (`base_hash`) plus its lineage (`version_id`, `origin_cid`,
  `ts`) — `FileVersion`, persisted in a private `.hsyncstate` side-car
  (`SyncStateStore`), **never exchanged on the wire**.
- `resolve_three_way(local, remote, base)` compares hashes only (immune to clock
  skew): only-local-changed → upload, only-remote-changed → download, both
  changed → **conflict**, no base → fall back to the legacy mtime/hash heuristic.
- **Conflict-first**: on genuine divergence the remote (master) wins, but the
  local content is always preserved as `<stem>_conflicted_copy_<ISO8601-UTC>_<cid>.<ext>`
  before any overwrite — no silent data loss. The naming convention is unified
  between client (`_save_conflict_copy`) and server (`upload.py`) and always
  uses UTC timestamps to avoid cross-timezone ambiguity. A `conflict_resolved`
  UI event is emitted so the Desktop GUI can surface the conflict immediately.
- The base is recorded after each successful sync, cleared on deletion and kept
  bounded via `retain()`. Android mirrors all of this (`util/Version.kt`).

## Consequences

- Fast-forward updates are distinguished from true conflicts, so conflict copies
  are created only when both sides really diverged, not on every mtime tie.
- Resolution no longer depends on synchronised clocks; the base hash, not the
  timestamp, decides direction.
- The model is deliberately *not* a CRDT: in ambiguous cases the master wins by
  design ([ADR-0001](0001-server-vs-lan-modes.md)), trading theoretical
  conflict-free merge for simplicity and predictability.
- Version state stays private per peer, so it imposes nothing on the wire
  contract ([ADR-0005](0005-protocol-versioning.md)). Scenarios (skew, concurrent
  divergence, reconvergence) are covered by `tests/test_version.py`,
  `TestThreeWayMergeEndToEnd` and Android `VersionTest.kt`.
