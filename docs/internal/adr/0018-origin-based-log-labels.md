# ADR 0018 — Origin-based log labels (`LOCAL ` / `REMOTE `) with unified verbs

- **Status:** Accepted
- **Date:** 2026-08-05
- **Supersedes (terminology):** the `LAN_*` / `CLIENT_*` label terminology used
  in [ADR 0017](0017-lan-slave-outbound-event-reliability.md).

## Context

The log line vocabulary made it impossible to tell **where a sync event
originated** at a glance:

- The `LAN ` prefix appeared on **both** sides with opposite meanings: the
  master's watcher lines (`[LAN MODIFY]`, `[LAN CREATE]`, …) and the slave's
  inbound dispatch lines (`[LAN DELETE]`, `[LAN SECURITY]`, `[LAN ECHO]`).
- The `CLIENT ` prefix was routinely misread as "slave-only", while the
  role is already implicit in which node produces the line.
- The same concept was expressed with different verbs: `[REMOVE]` (watcher,
  remote mode and master) vs `[DELETE]` (inbound dispatch), and the slave's
  abbreviated verbs (`UP`, `DEL`, `REN`, `DIR`, `NEW`, `IGN`, `KEEP`) formed
  near-duplicate pairs (`[CLIENT NEW]` vs `[LAN CREATE]`).

The remote (central-server) mode encoded origin implicitly and incoherently:
a locally-originated deletion logged `[REMOVE]` while the same deletion
received and applied from the server logged `[DELETE]`.

## Decision

### D1 — One verb vocabulary

Event stems are limited to `CREATE`, `MODIFY`, `RENAME`, `DELETE`, `SYMLINK`,
`IGNORE DEL`, `KEEP`. The role abbreviations (`UP`, `DEL`, `REN`, `DIR`,
`NEW`, `IGN`) are removed: the master/slave role is implicit in the prefix,
and the abbreviations produced pairs indistinguishable at a glance.

### D2 — The prefix encodes origin, in both modes

- `LOCAL ` — event originated by this node's local watcher;
- `REMOTE ` — event caused by a peer (the master for a slave, a slave for the
  master, the central server in remote mode).

The scheme applies to **both** LAN mode and the central-server mode. Extending
it to remote mode removes the `REMOVE`/`DELETE` dualism, needs no extra enum
members, and gives a single mental model. Accepted cost: the log lines of a
central-server sync change.

### D3 — Two-level rule

- **Prefixed labels** = events during continuous watching (local watcher or
  inbound dispatch).
- **Unprefixed labels** = reconciliation/full-scan phase, transfers, states,
  previews and `hsync-server` itself (`[DOWNLOAD]`, `[UPLOAD]`, `[RESUME]`,
  `[DELETE] "..." (not on master)`, `[IN SYNC]`, `[SKIP]`, `[PERMISSION]`,
  `[CONFLICT]`, `[GUARD]`, `[TOMBSTONE]`, `[SECURITY]`, `[TO ...]`,
  `[SYNCED]`, trust/election warnings, `[WS]`).

The "initial sync vs watching" distinction therefore stays readable, and
`hsync-server` needs no change (it only emits unprefixed, base members).

### D4 — No intent line on slave upload

A local save on a slave produced two INFO lines: the intent line
(`[CLIENT UP] "path" (CID: <own CID>)`) and the transfer line
(`[UPLOAD] "path" 4.0 KB`). The intent line is removed: its CID suffix always
carried this node's own CID (no information), and one line per action
mirrors the single `[DOWNLOAD]` line of the inbound path.

### Implementation notes

- `BaseFileEventHandler._label(name, src_path, dst_path)` computes the prefix
  by reusing the existing `_origin_cid()` hook (`"REMOTE "` when it returns a
  CID, else `"LOCAL "`); there is no static per-class `_LOG_PREFIX` anymore.
  The LAN master's `_origin_cid` already peeks the inbound-origin map without
  consuming it (the subsequent `_broadcast_event` still consumes for echo
  suppression), so no new hook and no second peek was needed.
- `EventDispatchContext.log_prefix` was removed: both inbound contexts would
  carry the same value, so it became dead configuration. A module constant
  `INBOUND_PREFIX = "REMOTE "` feeds `_tag(name)` instead.
- The `[MOVE]` debug trace stays unprefixed: it is an internal trace logged
  before the event is classified, not the propagated event.
- **Known limitation**: the inbound-origin marker TTL
  (`INBOUND_ORIGIN_TTL = 10.0`) means a watchdog event arriving after expiry
  prints `LOCAL` although peer-caused — the same degradation the `(CID: ...)`
  suffix already had, so prefix and CID degrade together and the line stays
  internally coherent. Documented in `docs/log-labels.md`.

## Consequences

### Benefits

- One glance tells the **origin** of every watching event, on every node, in
  every mode. The most frequent ambiguity (a slave upload seen on the master)
  now reads `[REMOTE MODIFY] ... (CID: slave-1)` instead of the identical
  `[LAN MODIFY]` used for local edits.
- The `REMOVE`/`DELETE` dualism and the abbreviated verb set are gone; the
  enum shrinks by two members net (18 removed, 16 added).
- The Kotlin mirror gains `REMOTE_DOWNLOAD`, closing a pre-existing parity
  drift (`LAN_DOWNLOAD` existed only in Python). `LogActionTest` now also
  asserts the mirror map is complete, so a future drift fails the test.

### Costs

- **Breaking change for external consumers**: user scripts, alerting or log
  filters matching `[LAN …]`, `[CLIENT …]`, `[REMOVE]` or the unprefixed
  watcher labels break. No internal consumer parses labels (only
  `colorize_labels` matches them for coloring). Declared in the three
  CHANGELOGs.
- **Redundancy accepted**: on the master, `REMOTE ` and the `(CID: ...)`
  suffix carry the same information; the prefix is for immediate readability
  and degrades together with the CID at TTL expiry.
- Central-server sync logs change (D2), beyond what the initial request
  covered — a deliberate choice to eliminate the dualism.

## References

- Canonical catalog: [`docs/log-labels.md`](../../log-labels.md)
- SSOT: `hsync_common/labels.py` (`ActionLabel`, `resolve_label`)
- [ADR 0017 — LAN slave outbound event reliability](0017-lan-slave-outbound-event-reliability.md)
  (its `CLIENT_*` terminology is superseded by this record)
- Kotlin mirror: `hsync-android/.../util/LogManager.kt` (`LogAction`)
