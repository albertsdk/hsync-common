# ADR 0055 — leadership terms, and a tie-break that knows its own error

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

[ADR-0054](0054-clock-free-election.md) took the clock out of the election and
[ADR-0027](0027-p2p-leadership-lease.md) decided that a partition may briefly
produce two serving masters (availability over at-most-one-master, no quorum).
That leaves three questions the two decisions do not answer:

1. **Which of two serving incumbents keeps the role when a partition heals?**
   `server_ready` is a boolean: both are serving, so the ordering falls through
   to operator flags and finally to the CID. The CID is deterministic, but it
   carries no information — a node that took over minutes ago and one that has
   been serving for a week have the same claim, and the loser yields purely
   because its identifier sorts higher.
2. **How long is a measured clock offset a reference?** A measurement is a claim
   about *the local clock at that moment*. A time daemon that steps the clock, a
   suspended VM, or a manual change makes the stored offset describe a clock that
   no longer exists, while the host still reports itself synchronised.
3. **How exact is "newer"?** A probe round-trip bounds how well the offset is
   known: with a 400 ms round-trip the offset is only good to ±200 ms, and the
   peer measured its own clock with a similar error. The tie-break therefore uses
   a fixed one-second guard: two corrected mtimes one second apart are not an
   order, yet they decided which file kept its name.

## Decision

### 1. Leadership is a term, and the term is on the wire

Every node advertises `epoch` — a **Lamport counter**, not a clock. A node that
starts serving sets its term to `max(term seen for the bucket) + 1`; a node that
never served advertises `0`. The election ordering becomes

`server_ready` → **highest `epoch`** → `prefer_master` → `inbound` →
bidirectional `sync_direction` → lowest `cid`

(`hsync_common.protocol.p2p::election_sort_key`). A serving incumbent still beats
a newcomer (readiness comes first, so a healthy mesh never churns); between two
*serving* incumbents the newer mandate wins and the older one yields through the
existing lease path, which is exactly the heal case. The term travels with the
other election fields: TXT `epoch`, `rdv/1` `register`/`peers[].epoch`
(`hsync-rendezvous/protocol-spec/rdv-1.md`). Nothing is persisted: a restarted
node re-acquires from the terms its peers advertise, and a lone node with no
peers has nothing to fence.

### 2. Sources are ranked, and the weakest one still helps

A reference is chosen by what it can prove about itself:

1. **The sync authority** — the `/api/v1/time` round-trip: the sync server in
   client-server mode, or the **elected master** in p2p (a slave adopts it only
   when the reply says `trusted: true`, i.e. the master is itself anchored).
   Explicit SNTP (`HSYNC_NTP_HOSTS`) is an **opt-in** deployment anchor for a
   serving node with no rendezvous, never a silent public-pool default. Every
   source bounds its estimate by the round-trip.
2. **The rendezvous echo** — a node answering `ack.server_time` is TLS-pinned and
   its reply already traverses the NAT, so it is reachable exactly where UDP/123
   is filtered. Its timestamp has one-second resolution, so the derived offset
   carries that quantization in its uncertainty, and a *better* source is never
   replaced by it: the echo only establishes trust where none exists. A node
   whose clock is off by more than an hour (`_ACK_MAX_OFFSET_S` in
   `hsync-client/hsync_client/timesync.py`) is refused rather than allowed to
   shift the mesh.
3. **Nothing** — the host stays degraded and content identity decides.

### 3. Trust has a shelf life, and a step revokes it

`ClockOffsetStore` (`hsync_common/clock.py`) now records *when* a measurement was
taken and degrades on its own:

* `is_trusted()` also requires `age() <= CLOCK_OFFSET_MAX_AGE_SECONDS`; an
  expired measurement is no longer a reference, which is why every role
  re-probes: the sync server and a p2p slave at the start of each `sync()`
  cycle, the serving master from its maintenance tick;
* `observe()` compares the wall clock against the monotonic clock on every
  sample `now_corrected()` takes. A divergence larger than
  `CLOCK_STEP_THRESHOLD_SECONDS` is a **step** (time daemon, manual change,
  suspend/resume), not drift: trust is revoked immediately and the next probe
  re-establishes it.

An untrusted host also stops **publishing** a timestamp: the corrected mtime it
would record and advertise becomes `0` ("unknown"). A value derived from a clock
the host cannot vouch for is stored by every peer and would compete again in the
tie-break once the clock recovered, so withholding it is what keeps a stale or
stepped clock out of the mesh's recorded history
(`hsync-client/hsync_client/sync_state.py::_corrected_mtime_of`,
`hsync-android/app/src/main/java/com/hsync/android/util/TimeSync.kt::TimeSync.advertisedCorrectedMtime`).

### 4. A difference inside the measurement error is not an order

`resolve_three_way` takes `mtime_uncertainty`: the chronological tie-break only
ranks two versions whose corrected mtimes differ by **more** than that bound.
The bound is the fixed, protocol-wide `CORRECTED_MTIME_TIE_BREAK_BOUND_SECONDS`,
never the evaluating host's own probe error: a per-node bound would let two
replicas disagree on the boundary and is not convergent. The producer withholds
the value (it advertises `0`) when its own measurement is untrusted, so the
comparator never reads local clock state. Inside the bound the deterministic
SHA-256 fallback decides, exactly as for an absent timestamp.

## Consequences

- A partition heal no longer hands the role to a node because of its identifier:
  the most recent mandate continues, which is what every Raft-derived system
  gets from the term of a log entry.
- The election stays clock-free: an epoch is a counter, and the ordering still
  consumes only per-candidate values (pinned by
  `hsync_common/tests/test_p2p_election_properties.py`).
- A host that cannot keep time honest stops being a time authority *by itself*
  (expiry, step) instead of only when it fails to reach a reference at startup.
- An expired offset is re-established on the next cycle/tick for every role, so
  a long-lived process never silently degrades to the hash fallback after the
  measurement expires.
- Two edits closer together than the probe's error resolve by content. That is
  the intended trade: a deterministic, comparable outcome beats a
  chronologically plausible coin flip. Users who want finer resolution need a
  reference with a tighter round-trip, not a looser rule.
