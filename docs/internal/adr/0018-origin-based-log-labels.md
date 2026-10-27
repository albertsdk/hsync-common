# ADR 0018 — Origin-based log labels (`LOCAL ` / `REMOTE `) with unified verbs

- **Status:** Accepted
- **Date:** 2026-08-05

## Context

A reader must be able to tell **where a sync event originated** at a glance, on
any node and in any mode. Encoding origin implicitly — via the master/slave role
or the mode — is ambiguous: the same line shape can mean a local edit on one
node and an applied peer event on another, and role-based prefixes (`P2P `,
`CLIENT `) are routinely misread as "master-only" or "slave-only" even though
the role is already implicit in which node produces the line.

The verb vocabulary must likewise be uniform: expressing the same concept with
different verbs (`[REMOVE]` vs `[DELETE]`), or with role abbreviations (`UP`,
`DEL`, `REN`, `DIR`, `NEW`, `IGN`), produces near-duplicate pairs that are
indistinguishable at a glance and force per-role mental translation.

## Decision

### D1 — One verb vocabulary

Event stems are limited to `CREATE`, `MODIFY`, `RENAME`, `DELETE`, `SYMLINK`,
`DEL KEPT`, `KEEP`. There are no role abbreviations: the role is implicit in
which node produces the line.

### D2 — The prefix encodes origin, in both modes

- `LOCAL ` — event originated by this node's local watcher;
- `REMOTE ` — event caused by a peer (the master for a slave, a slave for the
  master, the central server in server mode).

The scheme applies to **both** p2p mode and the central-server mode, so there is
a single mental model across modes.

### D3 — Two-level rule

- **Prefixed labels** = events during continuous watching (local watcher or
  inbound dispatch).
- **Unprefixed labels** = reconciliation/full-scan phase, transfers, states,
  previews and `hsync-server` itself (`[DOWNLOAD]`, `[UPLOAD]`, `[RESUME]`,
  `[DELETE] "..." (not on master)`, `[IN SYNC]`, `[SKIP]`, `[PERMISSION]`,
  `[CONFLICT]`, `[GUARD]`, `[TOMBSTONE]`, `[SECURITY]`, `[TO ...]`,
  `[SYNCED]`, trust/election warnings, `[WS]`).

The "initial sync vs watching" distinction therefore stays readable, and
`hsync-server` only emits unprefixed, base members.

### D4 — One line per action

A local save on a slave uploads and logs a single transfer line
(`[UPLOAD] "path" 4.0 KB`); the upload path carries no separate intent line,
mirroring the single `[DOWNLOAD]` line of the inbound path.

### Implementation notes

- `BaseFileEventHandler._label(name, src_path, dst_path)` computes the prefix
  by reusing the `_origin_cid()` hook (`"REMOTE "` when it returns a CID, else
  `"LOCAL "`); there is no static per-class `_LOG_PREFIX`. The p2p master's
  `_origin_cid` peeks the inbound-origin map without consuming it (the
  subsequent `_broadcast_event` still consumes it for echo suppression), so no
  second peek is needed.
- A module constant `INBOUND_PREFIX = "REMOTE "` feeds `_tag(name)` for inbound
  dispatch contexts.
- The `[MOVE]` debug trace stays unprefixed: it is an internal trace logged
  before the event is classified, not the propagated event.
- **Known limitation**: the inbound-origin marker TTL
  (`INBOUND_ORIGIN_TTL = 10.0`) means a watchdog event arriving after expiry
  prints `LOCAL` although peer-caused — prefix and CID degrade together and the
  line stays internally coherent. Documented in `docs/log-labels.md`.

## Consequences

### Benefits

- One glance tells the **origin** of every watching event, on every node, in
  every mode: a peer-caused edit reads `[REMOTE MODIFY] ... (CID: slave-1)`,
  while a local edit reads `[LOCAL MODIFY] ...`.
- A single, uniform verb set: no `REMOVE`/`DELETE` dualism and no role
  abbreviations.
- The Kotlin mirror exposes the same `LOCAL_*`/`REMOTE_*` vocabulary, including
  `REMOTE_DOWNLOAD`; `LogActionTest` asserts the mirror map is complete, so any
  drift fails the test.

### Costs

- Log filters and alerting that match label text must use the
  `[LOCAL …]`/`[REMOTE …]` vocabulary.
- **Redundancy accepted**: on the master, `REMOTE ` and the `(CID: ...)` suffix
  carry the same information; the prefix is for immediate readability and
  degrades together with the CID at TTL expiry.

## References

- Canonical catalog: [`docs/log-labels.md`](../../log-labels.md)
- SSOT: `hsync_common/labels.py` (`ActionLabel`, `resolve_label`)
- Kotlin mirror: `hsync-android/.../util/LogManager.kt` (`LogAction`)
