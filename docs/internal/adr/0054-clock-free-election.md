# ADR 0054 — the election never reads a clock, and chronology needs a measured one

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

The LAN master election ([ADR-0002](0002-p2p-master-election.md)) is a pure
ranking over advertised peer attributes, run identically on every node so the
whole mesh agrees on one master. Two of its inputs used to be temporal:

1. a **start-time tie-break**: among peers equal on readiness, operator
   preference, reachability and direction, the node that started earliest won;
2. the **chronological tie-break** of a true causal divergence
   ([ADR-0023](0023-corrected-mtime-tie-break.md)): the newer
   `corrected_mtime` kept the original path.

Both compare values produced by each host's own clock. The correction that makes
them comparable is a *measurement* (`hsync_common.clock`): an NTP round-trip to
the sync server, or SNTP probes against public hosts in p2p mode. When no
reference answers — an offline LAN, an air-gapped NAS, a network that filters
UDP/123 — the offset is 0 and the local clock is used as if it were true time.
Two hosts then compare unrelated clocks:

- a node whose clock runs fast always looks like "the earlier starter" and keeps
  mastership against every honest peer, and the outcome of the election depends
  on an accident of hardware rather than on policy;
- a `corrected_mtime` comparison between two unsynchronised hosts ranks
  arbitrary numbers, so the file that keeps the original path is chosen by clock
  skew rather than by chronology.

The election additionally advertised the start instant (`startup_time`) on the
mDNS TXT record and on the `rdv/1` `register`/`peers[]` frames, which made the
value part of the wire contract and of every cross-language fixture.

## Decision

**No decision may read a clock unless a reference measured it.**

1. The election ordering is `server_ready` → `prefer_master` → `inbound` →
   bidirectional `sync_direction` → lowest `cid`
   (`hsync_common.protocol.p2p::election_sort_key`). Continuity comes from
   `server_ready` (a serving incumbent keeps the role), operator intent from
   `prefer_master`, and a cold start is decided by `cid`, which every host reads
   identically. `startup_time` is removed from the candidate, from the TXT
   record, from `rdv/1` and from every mirror.
2. The chronological tie-break runs only when the local clock is trusted:
   `ClockOffsetStore.is_trusted()` is true exactly when a reference produced the
   offset in force (`record(offset, trusted=True)`), false in degraded mode
   (`record(0.0, trusted=False)`). An untrusted host feeds `0` for both sides
   (`hsync_common.models.arbitration::decide_arbitration`,
   `hsync_client.sync::_chronological_inputs`), which is the documented
   "unknown mtime" path: content identity decides, so every peer still converges
   on the same winner.
3. No quorum is introduced. A partition can still yield two serving masters
   ([ADR-0027](0027-p2p-leadership-lease.md)); the guarantee is that the
   *convergence on heal* is deterministic and clock-free, and that divergence is
   bounded by causal reconciliation ([ADR-0022](0022-causal-vector-clock-conflict-model.md)).

## Consequences

- A mis-set or unsynchronised clock can no longer buy mastership, keep it, or
  decide which file keeps its name. Degraded temporal mode changes *which*
  deterministic rule decides (content identity), never *whether* peers agree.
- The election has one fewer input and one fewer wire field; the TXT record and
  the `rdv/1` frames carry only facts a peer can observe about itself and that
  mean the same thing on every host.
- Without a measured clock, two concurrent edits of the same path resolve by
  SHA-256 instead of by time: the losing version becomes a
  `_conflicted_copy_` exactly as before, but the *choice* is no longer
  chronological. Users who need chronological arbitration must let the client
  reach a time reference (the sync server, or the configured SNTP hosts).
- The clock module now reports trust (`ClockOffsetStore.is_trusted`), which is
  also the signal a front-end can surface as "degraded temporal mode".
