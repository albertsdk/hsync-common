# ADR 0030 — p2p seeder capacity advertisement and requester admission

- **Status:** Accepted
- **Date:** 2026-09-16

## Context

[ADR-0028](0028-p2p-peer-assisted-download.md) gives p2p slaves a read-only
seeder and a master-mediated source lookup with a bounded per-seeder
response-body concurrency (`HSYNC_P2P_PEER_READ_CAP`, default 2, range 1–32),
but a requester cannot *learn* that bound. A saturated seeder answers `503`
before opening the file, so a requester would discover the limit only by
provoking refusals — and if every refusal were priced like a health failure (an
exponential exclusion of up to 60 s that also drops the source from ranking), a
burst of small files would become a storm of refused attempts and the rest of
the cycle would fall back to the master. Capacity must therefore be advertised,
and a full seeder must be a scheduling outcome, never a failure.

The L2 loopback benchmark (`hsync-client/bench/bench_p2p_peer_transfer.py`, cycle
scenario) quantifies it: with cap 2 and 8 warm workers, 24-file cycles produced up
to 4 `503` per cycle and up to 23 of 168 downloads served by the master instead of
a peer. The same benchmark shows the warm peer path is latency-equivalent to the
master (≤ ~1.2 ms apart at every size from 4 KiB to 8 MiB), so the size threshold
is not the lever — the refusal handling is.

## Decision

We will make the seeder's capacity part of the contract instead of something the
requester discovers by being refused:

1. A serving node advertises `serve_slots` (integer, 1–32) on the authenticated
   p2p WebSocket handshake (`P2PAuthFrame`/`P2PHelloFrame`). The field is present
   exactly when the node serves peer downloads: omitting it means "not a source
   candidate". No TXT key is added.
2. The master records the advertisement with the publisher session
   (`P2PInventoryStore.begin_session(..., serve_slots=...)`) and returns it in
   every `POST /files/sources` candidate (`P2PSourceCandidate.serve_slots`, now
   required). A candidate cannot exist without a live advertisement, so the
   requester always knows the limit it must respect. An inconsistent frame
   (non-integer or out-of-range value, or slots without the `peer_download`
   capability) is refused as a protocol violation on both masters.
3. The requester admits at most `serve_slots` concurrent reads per CID, waiting up
   to a bounded interval (`P2P_PEER_SLOT_WAIT_S`, 2 s) for a slot before taking the
   master. Expiring that wait is a *scheduling* outcome, never a refused attempt.
   Candidates are ordered by the **predicted transfer cost**
   (`setup + size/bandwidth`, both already measured per source) instead of a raw
   throughput rate, so the ordering follows the file at hand rather than the size
   of whatever that peer happened to serve last.
4. A `503` remains a safety net: the seeder sends `Retry-After` and the requester
   defers that source for exactly that interval without incrementing its failure
   count or dropping it from ranking. Real health failures keep the existing
   exponential exclusion.
5. The Android client mirrors the field, the session storage, the master echo, the
   slave advertisement and the requester admission (per-CID slot gate plus a
   `Retry-After` deferral); the golden fixtures are shared verbatim.
6. There is no size threshold. `serve_slots` plus the cost-ordered ranking is
   what decides whether a peer is worth using, so no
   `HSYNC_P2P_PEER_DOWNLOAD_MIN_SIZE` knob exists in any artifact (settings
   model, environment contract, man page, WD OS5 installer/UI, Android
   `SyncConfig`, benchmark scenarios).
7. Admission waits for a slot (bounded by `P2P_PEER_SLOT_WAIT_S`) instead of
   declining immediately. Returning at once sends every worker above a seeder's
   capacity straight to the master, which is the outcome peer download exists to
   avoid: measured on the cycle scenario, non-blocking admission served 6.7 of 24
   files from the peer and 121 of 168 full downloads from the master, against
   24 of 24 and 0 of 168 while waiting.
8. There is no `seed` TXT hint. Whether a peer can serve is decided by its
   authenticated session with the master, so a discovery-time copy of that fact
   can only ever be stale and could exclude a seeder that is in fact serving. A
   serving slave still advertises `https`/`cert_fp` (endpoint material) from the
   same "endpoint bound" state, so no requester loses the route to a seeder.

## Consequences

- No `503` storm: a requester never exceeds the advertised capacity, so a wide
  worker pool does not degenerate into refused attempts plus a long exclusion.
- Capacity travels end to end over authenticated channels (seeder → master →
  requester). A stale or spoofed value can at worst cause a failed attempt
  followed by the mandatory master fallback.
- The candidate field is **required**: a node that does not advertise is not a
  candidate.
- No size heuristic, no user-facing knob: peer assistance is enabled by default
  (`HSYNC_P2P_PEER_DOWNLOAD`, `--no-peer-download`) and every listed file is
  eligible for a lookup. A small file uses the peer path whenever a seeder has a
  free slot and its predicted cost is competitive. `HSYNC_P2P_PEER_READ_CAP`
  bounds how much a seeder gives away, announced on the handshake rather than
  guessed.
- An environment that still sets `HSYNC_P2P_PEER_DOWNLOAD_MIN_SIZE` is ignored,
  in line with the project's no-backward-compatibility stance.
- The TXT contract carries no `seed` key: the client's service listener/snapshot
  model and the Android mirror do not consult a browser-cached hint that could
  contradict live state.
- **The Android mirror implements the same admission shape, plus bounded bulk
  parallelism.** Its downloader waits up to 2 s for a seeder's advertised slot and
  then for an app-wide bound of four concurrent peer reads (per-seeder capacity is
  claimed first, so one hot seeder cannot hold global capacity while queued),
  falling back to the Primary only when the wait expires — the behaviour point 7
  mandates, measured in `hsync-client/bench_p2p_peer_transfer.py --latency`. Its
  sync cycle downloads four files at a time instead of sequentially: the same
  benchmark prices that at 3.1× less wall time on loopback and 3.6× behind a 40 ms
  RTT for the master path, which is where the sequential loop's per-file round trip
  dominated.
- New obligations: strict validators, schemas and shared fixtures in
  `hsync-common`; admission/busy semantics plus the cycle acceptance scenario in
  `hsync-client`; contract parity tests in `hsync-android`.
- **Worker-to-seeder affinity is rejected on measurement.** The follow-up idea —
  group a cycle's downloads per candidate seeder so each seeder is served by as
  many workers as its slots instead of by the whole pool — does not pay: driven
  through one long-lived pool behind a latency relay
  (`bench_p2p_peer_transfer.py --latency`, 24 × 4 KiB per cycle, cap 2), a cycle
  pays handshakes only at first contact (`[2,0,…]` with 2 workers, `[8,0,…]` with
  8) and **zero** afterwards, because the HTTP session cache is per-thread and
  every worker keeps a warm keep-alive connection. Forcing the worker count down
  to the slot count under a 40 ms RTT costs 1066.6 ms per cycle against 815.6 ms
  with 8 workers, so affinity would trade 6 one-time handshakes for a permanent
  parallelism loss. Admission stays as specified in point 3; `sync.py` keeps its
  single shared pool, and no grouping/scheduling layer is added. The remaining RTT
  cost is the per-file request round trip, which is out of this decision's scope.
