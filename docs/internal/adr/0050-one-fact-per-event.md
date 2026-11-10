# ADR 0050 — One fact per event: link state and data movement

- **Status:** Accepted
- **Date:** 2026-11-10

## Context

The `--events-json-fd` channel is the only state source a front-end has. Two
facts a user watches are independent:

- whether the **link** to the peer/server is up (`disconnected`, `connecting`,
  `connected`, `waiting`, `error`);
- whether the engine is currently **moving data** (a sync cycle is running, or
  nothing is in flight).

They change on different triggers and at different rates: a cycle starts and
ends many times while the link stays up, and the link can drop without any cycle
being planned. Carrying both in one `status` field forces each value to overwrite
the meaning of the other, and the consumer has to reconstruct one fact from the
other's transitions.

## Decision

The channel carries one fact per event, each with exactly one publisher that also
owns its state:

- `status` — the link state. Published by `set_link_status`
  (`hsync-client/hsync_client/events.py::set_link_status`), which drops a repeat
  of the current value, so the stream is a sequence of transitions.
- `activity` — the data-movement phase (`syncing`/`idle`). Published by
  `begin_activity` / `end_activity`
  (`hsync-client/hsync_client/events.py::begin_activity` /
  `hsync-client/hsync_client/events.py::end_activity`) from a counter of cycles in
  flight, so overlapping cycles report `syncing` once and `idle` only when the
  last one ends.

`status` is published by whoever establishes the link — the remote handshake, the
REST round that proves the data plane, the p2p master/slave transitions — and
`activity` is published by `sync()`
(`hsync-client/hsync_client/sync.py::sync`) for every mode: remote, p2p lan and
p2p over a rendezvous relay. No module publishes either event directly;
`hsync-client/tests/test_events.py::test_status_and_activity_have_exactly_one_publisher`
pins that.

## Consequences

- A cycle running on a live link leaves `status` at `connected`: the front-end
  keeps a truthful link indicator and shows the phase on its own surface.
- A deduplicated publisher never desynchronizes from the stream: a bypassing
  publisher would move the consumer without moving the module state, and the next
  real transition would be dropped as a repeat.
- Adding a third fact means adding a third event (and its funnel), never a new
  value on an existing one — the extension mechanism of ADR-0004.

## References

- `hsync-common/hsync_common/protocol/events.py::UiEventName`
- ADR-0004 (Desktop subprocess contract)
