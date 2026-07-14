# ADR 0030 — LAN seeder capacity advertisement and requester admission

- **Status:** Accepted
- **Date:** 2026-09-16

## Context

ADR-0028 gave LAN slaves a read-only seeder and a master-mediated source lookup
with a bounded per-seeder response-body concurrency (`HSYNC_LAN_PEER_READ_CAP`,
default 2, range 1–32) — but no way for a requester to *learn* that bound. A
saturated seeder answers `503` before opening the file, so the requester could only
discover the limit by provoking refusals, and every refusal was classified
`PeerFailureKind.busy` and priced like a health failure: an exponential exclusion
of up to 60 s that also removed the source from ranking. A burst of small files
therefore turned into a storm of refused attempts, after which the rest of the
cycle fell back to the master.

The L2 loopback benchmark (`hsync-client/bench/bench_lan_peer_transfer.py`, cycle
scenario) quantifies it: with cap 2 and 8 warm workers, 24-file cycles produced up
to 4 `503` per cycle and up to 23 of 168 downloads served by the master instead of
a peer. The same benchmark shows the warm peer path is latency-equivalent to the
master (≤ ~1.2 ms apart at every size from 4 KiB to 8 MiB), so the size threshold
is not the lever — the refusal handling is.

## Decision

We will make the seeder's capacity part of the contract instead of something the
requester discovers by being refused:

1. A serving node advertises `serve_slots` (integer, 1–32) on the authenticated
   LAN WebSocket handshake (`LanAuthFrame`/`LanHelloFrame`). The field is present
   exactly when the node serves peer downloads: omitting it means "not a source
   candidate". No TXT key is added.
2. The master records the advertisement with the publisher session
   (`LanInventoryStore.begin_session(..., serve_slots=...)`) and returns it in
   every `POST /files/sources` candidate (`LanSourceCandidate.serve_slots`, now
   required). A candidate cannot exist without a live advertisement, so the
   requester always knows the limit it must respect. An inconsistent frame
   (non-integer or out-of-range value, or slots without the `peer_download`
   capability) is refused as a protocol violation on both masters.
3. The requester admits at most `serve_slots` concurrent reads per CID, waiting up
   to a bounded interval (`LAN_PEER_SLOT_WAIT_S`, 2 s) for a slot before taking the
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
6. The size threshold is deleted rather than retuned. `serve_slots` plus the
   cost-ordered ranking is what decides whether a peer is worth using, so
   `HSYNC_LAN_PEER_DOWNLOAD_MIN_SIZE` is removed end to end together with every
   artifact that carried it (settings model, environment contract, man page,
   WD OS5 installer/UI, Android `SyncConfig`, benchmark scenarios). No shim
   reads the old variable.
7. Admission waits for a slot (bounded by `LAN_PEER_SLOT_WAIT_S`) instead of
   declining immediately. Returning at once sends every worker above a seeder's
   capacity straight to the master, which is the outcome peer download exists to
   avoid: measured on the cycle scenario, non-blocking admission served 6.7 of 24
   files from the peer and 121 of 168 full downloads from the master, against
   24 of 24 and 0 of 168 while waiting.
8. The `seed` TXT hint is removed. Whether a peer can serve is already decided by
   its authenticated session with the master, so a discovery-time copy of that
   fact can only ever be stale — and because candidacy *required* it, a lagging
   record could exclude a seeder that was in fact serving. A serving slave still
   advertises `https`/`cert_fp` (endpoint material) from the same "endpoint bound"
   state, so no requester loses the route to a seeder.

## Consequences

- No `503` storm: a requester never exceeds the advertised capacity, so a wide
  worker pool no longer degenerates into refused attempts plus a long exclusion.
- Capacity travels end to end over authenticated channels (seeder → master →
  requester). A stale or spoofed value can still at worst cause a failed attempt
  followed by the mandatory master fallback.
- The candidate field is **required** (no compatibility shim): a node that does not
  advertise is not a candidate.
- The retired size heuristic leaves no user-facing knob behind: peer assistance
  stays enabled by default (`HSYNC_LAN_PEER_DOWNLOAD`, `--no-peer-download`) and
  every listed file becomes eligible for a lookup. A small file now uses the peer
  path whenever a seeder has a free slot and its predicted cost is competitive,
  which is exactly the small-file burst the threshold used to divert to the
  master. `HSYNC_LAN_PEER_READ_CAP` continues to bound how much a seeder gives
  away, and it is announced on the handshake rather than guessed.
- Deleting the knob is a breaking configuration change: an environment still
  setting `HSYNC_LAN_PEER_DOWNLOAD_MIN_SIZE` is ignored, in line with the
  project's no-backward-compatibility stance.
- One fewer discovery key: `seed` leaves the TXT contract, the client's service
  listener/snapshot model and the Android mirror, and candidacy no longer consults
  a browser-cached hint that could contradict live state.
- New obligations: strict validators, schemas and shared fixtures in
  `hsync-common`; admission/busy semantics plus the cycle acceptance scenario in
  `hsync-client`; contract parity tests in `hsync-android`.
- **Worker-to-seeder affinity was evaluated and rejected on measurement.** The
  follow-up idea — group a cycle's downloads per candidate seeder so each seeder
  is served by as many workers as its slots instead of by the whole pool — does
  not pay: driven through one long-lived pool behind a latency relay
  (`bench_lan_peer_transfer.py --latency`, 24 × 4 KiB per cycle, cap 2), a cycle
  pays handshakes only at first contact (`[2,0,…]` with 2 workers, `[8,0,…]` with
  8) and **zero** afterwards, because the HTTP session cache is per-thread and
  every worker keeps a warm keep-alive connection. Forcing the worker count down
  to the slot count under a 40 ms RTT costs 1066.6 ms per cycle against 815.6 ms
  with 8 workers, so affinity would trade 6 one-time handshakes for a permanent
  parallelism loss. Admission stays as specified in point 3; `sync.py` keeps its
  single shared pool, and no grouping/scheduling layer is added. The remaining RTT
  cost is the per-file request round trip, which is out of this decision's scope.
