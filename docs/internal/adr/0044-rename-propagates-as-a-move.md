# ADR 0044 — A rename propagates as a move, never as a re-upload

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

A rename is a content-preserving operation, but a sync engine only observes its
two halves: one path disappears and another appears. Both transports already
propagated a *live* rename as a move (a `renamed` WebSocket event in server
mode, `PATCH …/files?src&dst=` on the p2p master), yet a rename performed while
the peer was **not watching** — offline, during a one-shot run, or through a
watcher that cannot observe moves (an Android SAF tree) — reached the reconcile
loop as a tombstone-confirmed `delete_remote` plus an `upload`. The file was
then deleted on the peer and re-sent in full: the single most expensive way to
express "the same bytes, another name".

The information needed to do better was already in hand: the remote listing
advertises `sha256sum` + `size`, and the local scan computes the same hash, so
the two halves of a rename are recognisable without any extra round trip.

The receiving side had the mirror optimisation already (`split_rename_pairs` +
`_apply_local_rename`: a tombstone-confirmed delete plus a download of identical
content becomes one local `os.replace`), which made the asymmetry visible.

## Decision

**Pair, then move on the side that holds the bytes.** A reconcile cycle pairs
every vacated path with a new path carrying the same `(sha256, size)` and, for
the outbound direction, asks the peer to move its own copy over
`PATCH …/files?src=&dst=`. One contract covers the central server and the p2p
master — the server endpoint was added rather than inventing a second shape.

The move is **causal, not merely physical**, so offline peers converge too:

- the source path gets a deletion marker (a rename vacates it exactly like a
  delete), and the destination's stale markers are dropped;
- the stored version clock travels to the new path **unchanged** — a rename is
  not an edit, so it must not tick a new lineage;
- `mtime`/`permissions` travel with the request, so the destination converges
  the metadata an upload would have applied;
- the response carries the destination entry plus that version, which the caller
  records as its new merge base.

Guards, because a remote move is only correct when it is provably the same
content:

- `expected_sha256` on the wire, checked by the peer, so a stale listing can
  never relocate bytes nobody verified;
- the local file is re-hashed immediately before the call (the listing predates
  the transfer phase: a concurrent edit must fall back to an upload rather than
  publish the pre-edit content at the new path);
- a destination that already exists is a conflict, never an overwrite;
- any refusal (409, 404/405, transport error) falls back to delete + upload, so
  the optimisation can only save bytes, never change the outcome.

The preview pairs through the same function as the cycle, so the plan a
confirmation shows and the plan the run executes cannot disagree (ADR-0043).

## Consequences

### Benefits

- Renaming a file — or a whole directory, which is one pair per file, i.e. N
  zero-byte requests instead of N uploads — costs no content bandwidth in either
  direction, and the peers that were offline during the rename do not download
  it either.
- The peer stays the authority over its own tree: it verifies the checksum and
  refuses a destination it already has.
- One request shape for server mode and p2p mode.

### Costs and limits

- A directory rename is N file-level moves (a single directory-level PATCH would
  need a client-side prefix move of the version store; the zero-byte property is
  already achieved, so the round-trip count is the remaining cost).
- A rename whose content also changed is not a rename for this purpose (the
  hashes differ): it stays a delete + upload, which delta transfer may still
  shrink.
- Symlinks are excluded — they replicate structurally (path + target) through
  the symlink surface and never move bytes anyway.

## References

- Server endpoint: `hsync-server/hsync_server/api/files/rename.py::rename_file`
- P2P master: `hsync-client/hsync_client/p2p_server.py::P2PEndpointMixin._handle_rename`
- Client action: `hsync-client/hsync_client/transfer.py::rename_file_remote`
- Pairing (shared with the preview): `hsync-client/hsync_client/sync.py::split_rename_pairs`
- Cycle wiring: `hsync-client/hsync_client/sync.py::_apply_remote_rename`,
  `hsync-client/hsync_client/sync.py::_apply_local_rename`
- Causal state: `hsync-server/hsync_server/versions.py::move_version`,
  `hsync-client/hsync_client/sync_state.py::move_base`
- Related: ADR-0003 (tombstones), ADR-0022 (vector clocks), ADR-0023
  (corrected mtime), ADR-0043 (preview contract)
