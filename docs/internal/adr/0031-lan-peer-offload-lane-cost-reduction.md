# ADR 0031 — LAN peer-offload lane cost reduction

- **Status:** Proposed (revised by the Phase 0 attribution below; implementation
  gated on an independent review)
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

## Decision

We will **not** move the seeder (or the whole lane) to a separate process: the
attribution shows neither is the cost. Instead, reduce the two measured costs
directly, each gated on the same reproducible harness and on the ADR-0028
boundaries above:

1. **Resolver (apply workers).** Stop the per-file source lookup from blocking
   an apply worker. The lookup only chooses a *source*; the master is always a
   valid fallback, so the requirement is to keep the same observable outcome
   (best-effort peer source, transparent master fallback) while removing the
   synchronous POST from the worker's critical path — e.g. an already-warm
   candidate cache consulted without a forced refresh, or an asynchronous lookup
   whose result is applied to a later transfer. Whichever design is chosen must
   preserve exact-`(path, sha256)` identity, live-session checks, and the
   bounded/sequenced inventory contract.
2. **Publisher (event loop).** Reduce the inventory publication work scheduled on
   the loop that carries sync events (snapshot/delta encoding and ACK handling),
   without weakening the gen/seq/ACK ordering or the bounded-retry semantics.

The defaults, the protocol, the master's authority, and `--no-peer-download`
(the explicit opt-out) are unchanged.

## Consequences

- The Phase 0 harness is committed and reusable; it corrected the design before
  any code change, which is the point of gating on it.
- Both targeted reductions are internal and semantics-preserving if the
  ADR-0028 boundaries are honoured; each needs a regression test and an A/B.
- If neither reduction pays, the correct outcome is to keep the default and
  leave `--no-peer-download` as the supported trade-off — not to add process
  isolation for a cost it does not address.
