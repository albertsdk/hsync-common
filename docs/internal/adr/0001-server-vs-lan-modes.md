# ADR 0001 — Two sync modes: central server vs LAN P2P

- **Status:** Accepted
- **Date:** 2026-06-21

## Context

HSYNC must serve two very different deployments with one codebase:

- A **central, always-on server** reachable over the internet (the FastAPI
  `hsync-server`), where many clients sync against an authoritative endpoint.
- A **local network with no fixed server**, where peers (desktops, an Android
  phone) should sync directly without standing up infrastructure.

A single transport cannot satisfy both: the server case wants a stable URL,
TLS and accounts; the LAN case wants zero-config discovery and a master elected
on the fly. Conflating them would push internet-only concerns (e.g. a mandatory
server) onto LAN users and LAN concerns (e.g. mDNS) onto server deployments.

## Decision

We will support **two explicit sync modes** behind a shared data/protocol core:

- **Server mode** — clients talk REST + WebSocket to `hsync-server`, the single
  authoritative endpoint.
- **LAN P2P mode** — peers self-discover over mDNS/TXT and **elect a master**
  among themselves (see [ADR-0002](0002-lan-master-election.md)); the elected
  master plays the authoritative role for that bucket.

Both modes reuse the same `hsync-common` models, the same conflict model
([ADR-0006](0006-master-authoritative-conflict-model.md)) and the same
versioned protocol contract ([ADR-0005](0005-protocol-versioning.md)). LAN mode
is opt-in (`--lan-mode`); server mode is the default.

## Consequences

- One node is always authoritative (the server, or the elected LAN master), so
  reconciliation rules are identical regardless of mode.
- LAN mode carries discovery, election and trust concerns that do not exist in
  server mode; these are isolated in `hsync_client.lan` and the
  `hsync_common.protocol.{lan,pairing}` SSOT, not sprinkled through core sync.
- The desktop UI must reflect which controls apply to which mode; it gates LAN
  controls on advertised binary capabilities ([ADR-0004](0004-desktop-subprocess-contract.md)).
- Security posture differs by mode: the LAN channel is designed for a trusted
  LAN and degrades safely on untrusted networks (TOFU pinning, write-key policy,
  strict pairing) — see [lan-protocol.md](../../lan-protocol.md).
