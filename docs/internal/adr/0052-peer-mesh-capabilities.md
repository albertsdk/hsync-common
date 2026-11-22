# ADR 0052 — The peer mesh has three capabilities, not one

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

A device participates in the p2p mesh in three independent ways: it can **serve**
file blocks to other devices (egress), **fetch** them from other devices
(ingress), and **publish** the read-only inventory the serving device classifies
the share against (metadata egress). Each answers a different operator question —
upload cost, download path, and privacy — and each is observable on the wire:
`Capability.peer_download` and the mDNS TXT `peer_download` for serving, the
per-session `serve_slots` capacity for serving now, and
`Capability.publishes_index` for publishing.

A single `--no-peer-download` / `HSYNC_P2P_PEER_DOWNLOAD` switch collapsed the
three. It made "I will not upload" and "I will not download from peers"
inseparable, so a device could not be a pure consumer without also losing its
sources, and the capability advertisement (`index` meant both "speaks the
inventory protocol" and "publishes an inventory") could not be derived from
what the device actually does.

## Decision

One key per capability, all defaulting to on, each advertised on its own surface
(`hsync-client/hsync_client/peer_roles.py` is the single reader):

- `P2P_SERVE_BLOCKS` / `--no-serve-peer-blocks` — the seeder role, its endpoint
  readiness, the `serve_slots` capacity, the TXT flag and the `peer_download`
  capability.
- `P2P_FETCH_FROM_PEERS` / `--no-fetch-from-peers` — the source resolver. Local
  policy: no peer learns it.
- `P2P_PUBLISH_INVENTORY` / `--no-publish-inventory` — the inventory publisher
  and `Capability.publishes_index`. A device that does not publish is admitted
  without an inventory session, and still advertises `index`: that token states
  protocol support, not participation.

`--peer-role full|leech|seed|off` bundles the three for front-ends (Desktop
switch group, NAS web UI), and an explicit `--no-*` flag always wins because the
flags can only turn a capability off. The Internet-visible analogue of the
rejected alternative is the single "peer downloading" bit: it reads well until
someone needs *one* of the three.

## Consequences

- Every gate derives from one of three functions, so a new call site cannot
  invent a fourth meaning; the wire keeps one token per observable behaviour and
  the master validates the `serve_slots`/`peer_download` pair it receives.
- The capability set is no longer a single bit to mirror: `hsync-common`
  declares `publishes_index`, the committed schemas/fixtures carry it, and
  Android mirrors the token and the three settings (`Protocol.kt`,
  `hsync-android` settings screen).
- Operators must set three keys to reproduce "peer mesh off"; the preset exists
  for that, and each front-end documents the matrix.
- A device that publishes no inventory is reported by the serving device without
  its rows: that consequence is a documented trade-off of the privacy switch, not
  a defect.
