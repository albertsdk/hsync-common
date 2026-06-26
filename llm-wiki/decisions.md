# hsync-common — Decisions

Ecosystem-wide architectural decisions are recorded as ADRs under
[`../docs/adr/`](../docs/adr/README.md) (committed, human-readable). They are the
*why* behind the SSOT this library exposes. This page is the agent index mapping
each ADR to the code it governs.

| ADR | Governs (code) |
| --- | -------------- |
| [0001 server-vs-lan-modes](../docs/adr/0001-server-vs-lan-modes.md) | client run modes; LAN stack vs REST stack |
| [0002 lan-master-election](../docs/adr/0002-lan-master-election.md) | `protocol/lan.py:67` (`election_sort_key`, `elect_master`) |
| [0003 tombstone-gossip](../docs/adr/0003-tombstone-gossip.md) | `models/tombstone.py:49` (LWW merge, TTL, hashed keys) |
| [0004 desktop-subprocess-contract](../docs/adr/0004-desktop-subprocess-contract.md) | `protocol/events.py` event stream; `protocol/capabilities.py` |
| [0005 protocol-versioning](../docs/adr/0005-protocol-versioning.md) | `protocol/handshake.py:44` (versions + hard-fail handshake) |
| [0006 master-authoritative-conflict-model](../docs/adr/0006-master-authoritative-conflict-model.md) | `models/version.py:70` (`resolve_three_way`) |

LAN transport/security specifics (TOFU pinning, LAN-key policy, threat model)
live in [`../docs/LAN_PROTOCOL.md`](../docs/LAN_PROTOCOL.md) and map to
`protocol/pairing.py` + `ssl_utils.py`.

## House rules (from `CLAUDE.md`)

- **Zero backward compatibility**: no shims/migration layers; consumers import
  `hsync_common.*` directly.
- **SSOT discipline**: protocol constants, election, pairing and models are
  defined only here; other repos mirror, never fork.
- New ADRs: copy [`../docs/adr/template.md`](../docs/adr/template.md), add to the
  ADR index and reference the governed code here.
