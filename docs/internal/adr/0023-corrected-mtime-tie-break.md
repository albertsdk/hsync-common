# ADR 0023 — Corrected-mtime chronological tie-break

- **Status:** Accepted
- **Date:** 2026-08-16

## Context

ADR-0022 established the causal vector-clock model and, for true concurrent
divergence (clocks that neither dominates), a **content-only tie-break**: the
highest SHA-256 wins the original path and the loser is preserved as a
``_conflicted_copy_``. That tie-break is perfectly deterministic and
convergent, but it is not *chronological*: when two users genuinely edit the
same file at the same time on different devices, the winner is decided by an
arbitrary hash, not by which edit is actually the most recent. A user whose
content loses simply because its digest sorts lower finds the outcome
opaque and surprising — the opposite of a user-friendly last-write-wins.

The wall clock cannot be used directly: device clocks skew, and a far-future
(or maliciously set) local clock would win every tie-break (conflict
engineering). A usable chronological tie-break therefore needs a *reliable*
shared time reference, measured per device.

## Decision

### 1. Clock offset subsystem

A clock offset (trusted remote clock − local clock) is measured and kept
process-local by ``hsync_common.clock``:

- **Client-server mode** — the HSYNC server (or the LAN master) is the time
  authority: an NTP-like HTTP round-trip against the existing
  ``/api/v1/time`` endpoint (``measure_clock_offset`` /
  ``compute_clock_offset``).
- **LAN P2P / no-server startup** — a configurable list of public SNTP
  servers (UDP, RFC 4330) is probed in order until one answers
  (``measure_clock_offset_ntp_multi``); the estimate is the median of several
  round-trips. The host list is overridable through the ``HSYNC_NTP_HOSTS``
  environment variable (comma-separated), with
  ``pool.ntp.org, time.cloudflare.com, time.google.com`` as defaults, so a
  failing server degrades to the next one.
- **Offline / air-gapped** — when every probe fails the offset is recorded as
  0 (raw local time) and a degraded-temporal-mode log is emitted;
  synchronisation proceeds normally.

The measurement is never persisted and never writes the system clock; it is
re-measured at every process start/handshake. Android mirrors the exact
algorithm in Kotlin (SNTP and HTTP/RTT).

### 2. ``corrected_mtime`` version metadata

`corrected_mtime = local_mtime + measured_offset`, computed **when a version
is recorded/advertised** (self-record and upload/listings/events metadata) and
carried alongside the vector clock:

- `FileVersion` (private side-car) and `VersionInfo` (wire form, inside
  `FileDict["version"]`) both gain the integer field.
- Wire parsing stays tolerant: an absent or malformed ``corrected_mtime``
  parses as 0 (unknown), which triggers the *hash fallback* — never a
  protocol error, consistently with ADR-0022 §7.
- No protocol-version bump: the field is optional metadata inside the
  `vector_clocks` capability payload (ADR-0005 / ADR-0022 §7).
- Receiver-side guard: a peer-supplied ``corrected_mtime`` far in the future
  relative to the receiver's corrected clock is clamped
  (`CORRECTED_MTIME_MAX_FUTURE_SKEW = 300 s`) so a mis-set or malicious peer
  cannot win every tie-break.

### 3. Tie-break rule

`resolve_three_way` gains ``local_corrected_mtime`` and
``remote_corrected_mtime`` keyword inputs. On true concurrent divergence:

1. If **both** sides carry a known corrected mtime (> 0), the **higher
   (more recent) value wins** the original path.
2. Otherwise — a side unknown (0), or the two values equal — the existing
   deterministic **SHA-256 fallback** decides, so every peer still converges
   on the same winner from the same inputs.
3. Causal dominance (upstream of the tie-break) is never overridden: the
   corrected mtime is consulted only for genuine divergence.

The losing content keeps the existing preservation contract (ADR-0021):
``<stem>_conflicted_copy_<ISO8601-UTC>_<cid>.<ext>`` and the
``conflict_resolved`` UI event.

### 4. Amendment of ADR-0022

ADR-0022 §3 ("Deterministic tie-break on true divergence") is amended: the
hash is now the *fallback* tie-break; the corrected mtime is the primary one
on true divergence. §3.4.5 of ADR-0022 (Sha fallback) otherwise unchanged.

## Consequences

- The tie-break is now chronological and user-explainable ("the most recent
  edit keeps the name"), while remaining deterministic and convergent.
- The raw wall clock still never decides: only offset-corrected values,
  produced from a shared time reference, enter the comparison.
- Offline peers degrade to the hash fallback (offset 0 ⇒ both sides
  unknown ⇒ deterministic hash), so an isolated LAN still converges safely.
- Cross-language parity is enforced through the regenerated
  `causal-resolution-scenarios.json` golden fixtures, replayed by Python and
  Android tests (ADR-0022 §Consequences).
- The ``HSYNC_NTP_HOSTS`` environment variable is surfaced in the WD OS5
  packaging web UI (config_get/config_set, i18n) in lockstep with the client.

## Related

- [ADR-0021](0021-server-conflicted-copy.md) — conflicted-copy preservation
- [ADR-0022](0022-causal-vector-clock-conflict-model.md) — causal model
  (amended at §3)
- `hsync_common/clock.py` — HTTP/NTP offset measurement, offset store,
  clamping
- `hsync_common/models/version.py` — `corrected_mtime` field and tie-break
- `hsync-client` (`sync_state.py`, `transfer.py`, `main_logic.py`,
  `lan_handler.py`) — probing and metadata propagation
- `hsync-server/arbitration.py` — upload arbitration consuming the field
