# ADR 0031 — LAN peer-offload lane cost: attribution and accepted trade-off

- **Status:** Accepted (2026-09-21; decision: keep the lane, accept the measured
  cost, `--no-peer-download` is the opt-out)
- **Date:** 2026-09-21

## Context

LAN synchronization moves full-file downloads through the elected master, with
an optional peer-assisted path layered on top
([ADR-0028](0028-lan-peer-assisted-download.md),
[ADR-0030](0030-lan-seeder-capacity-advertisement.md)). That lane is enabled by
default and consists of three parts inside the slave process:

1. a read-only HTTPS **seeder** (`LANServer` in seeder mode);
2. an **inventory publisher** that owns snapshot/delta state and sends
   `inventory` frames over the same WSS connection that carries sync events;
3. a per-file **source resolver** invoked from the apply path
   (`sync.update_file`).

The initial LAN burst is CPU-bound: the Python side serialises on ~1 core (GIL),
so throughput ≈ one core divided by per-file CPU. An A/B with
`--no-peer-download` (which disables the whole lane) measures **+41-51 % burst
throughput** and **−33 % slave CPU/file**.

Two boundaries from ADR-0028 must hold for any change here: peer download is a
**pure optimization** — the master is always the guaranteed fallback, content is
verified against the listing hash before atomic replacement, and seeder identity
is TOFU-pinned — and inventory publication is a **bounded, sequenced** contract
(gen/seq, quotas, staging TTL).

## Phase 0 result (2026-09-21)

A reproducible per-thread CPU sampler was added to the LAN stress harness
(`HSYNC_BB_STRESS_PROFILE_CPU=1`, plan §13.13) and run on the 2500-file probe,
lane on vs `--no-peer-download`, sampling `/proc/<slave-pid>/task/*/stat` across
the burst:

| arm | slave CPU | ms/file | throughput | top threads |
| --- | --- | --- | --- | --- |
| lane on | 16.52 s | **6.61** | 180.0 files/s | `asyncio_0..5` ≈1.6 s each, `python` (loop) 1.58 s |
| lane off | 11.26 s | **4.50** | 271.3 files/s | `asyncio_0..7` ≈1.1 s each |

Two facts follow and they **refute the "idle lane threads contend for the GIL"
hypothesis**:

- the **seeder is idle** (it serves nobody in a 2-peer burst), so a separate
  seeder process would not recover the block;
- the delta is ~2.1 ms/file split between the **apply workers** (the per-file
  source resolver lookup, ~0.5 s extra on each of the 8 `asyncio_*` workers) and
  the **event-loop thread** (the inventory publisher, +1.58 s). It is genuine
  per-file/per-event work, not idle-thread GIL contention.

Supporting isolated figures: the inventory observer is ~9 µs/event
(`_normalize_entry`), the resolver POST is ~1 ms/file, and the previously
reported batching of that POST was measured and reverted (it does not pay at the
default concurrency). A coalesced `_notify` and a single-`lstat`
`_normalize_entry` were implemented, A/B'd (median +4.5 %, inside the ±15 %
host spread) and reverted.

## Phase 1 result (resolver) — no safe client-side reduction (2026-09-21)

The resolver was re-examined against the code and the ADR-0028 boundaries:

- The **listing-driven reconcile is already optimal**: `_execute_parallel_transfers`
  resolves candidates once for the whole download set
  (`source_resolver.resolve(downloads)`) and calls `download_file` **without**
  `refresh_peer_sources` (default `False`), so it consults the warm cache and
  issues no per-file POST.
- The per-file POST lives only in the **realtime `update_file` path**
  (`refresh_peer_sources=source_resolver is not None`), where each event carries
  a single file: per-file peer offload then *requires* a per-file lookup. Its
  batching (a collection window shared by the concurrent workers) was
  implemented, measured and **reverted** — at the default concurrency the window
  rarely gathers more than ~1.5 callers while stalling the leader.
- Dropping the lookup would keep synchronization correct (the master is always
  the fallback) but would silently **disable peer offload for that file** — a
  feature regression, not a cost reduction, and the ADR-0028 decision makes
  peer download a first-class default, not a best-effort extra.
- A "no other peer is online, skip the lookup" heuristic is unavailable
  client-side (the slave has no peer-presence signal; only the master's
  inventory sessions know it), and adding one is a protocol change.
- Including candidates in the broadcast event is **unsound**: events are
  broadcast to every slave while candidates are per-requester and must exclude
  the recipient (ADR-0028 §6, ADR-0030), so a single broadcast frame cannot
  carry correct per-recipient candidate lists.

## Decision

We will **not** change the lane. The Phase 0 attribution shows the cost is
genuine per-file/per-event work (per-file peer lookup in the apply workers plus
inventory publication on the event loop), not idle-thread GIL contention, and
the only per-file reduction that keeps the ADR-0028 semantics is the source
lookup — whose batching does not pay at the default concurrency. There is no
safe client-side win, and the protocol alternative is unsound under the
broadcast model. The supported trade-off remains `--no-peer-download` for
deployments that do not need to serve other peers.

Any future attempt must be a **protocol-level** design (e.g. a per-connection
candidate push that respects the per-requester exclusion and the strict
endpoint bounds) recorded in its own ADR and reviewed independently; it is not
pursued here.

## Consequences

- The Phase 0 harness is committed and reusable; it corrected the design before
  any code change (seeder isolation was refuted) and then ruled out the
  resolver reduction, which is the point of gating on measurement.
- No synchronization semantics, protocol, defaults, or failure modes change.
- The measured cost of the peer-offload lane (~2.1 ms/file on this host, +41-51 %
  burst throughput when disabled) is accepted as the price of the feature; the
  opt-out is documented.
