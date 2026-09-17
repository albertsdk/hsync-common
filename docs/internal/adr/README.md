# Architecture Decision Records (ADR)

This directory records the **stable architectural decisions** of the HSYNC
ecosystem so they cannot drift silently across the separate repositories
(`hsync-common`, `hsync-server`, `hsync-client`, `hsync-desktop`,
`hsync-android`). The records live in `hsync-common` because that is the shared
single source of truth every other project depends on.

An ADR captures *why* a decision was made, not just *what* the code does: the
context that forced it, the option chosen over the alternatives, and the
consequences accepted. Code answers "how"; these records answer "why".

## Conventions

- One decision per file, named `NNNN-kebab-title.md` (zero-padded, monotonic).
- Use [`template.md`](template.md): **Context / Decision / Consequences** plus a
  status header.
- ADRs are **append-only**: never rewrite an accepted decision. To change one,
  add a new ADR and mark the old one *Superseded by* it.
- Status values: `Proposed`, `Accepted`, `Superseded`.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-server-vs-lan-modes.md) | Two sync modes: central server vs LAN P2P | Accepted |
| [0002](0002-lan-master-election.md) | Deterministic LAN master election | Accepted |
| [0003](0003-tombstone-gossip.md) | Causal tombstone gossip for deletions | Accepted |
| [0004](0004-desktop-subprocess-contract.md) | Desktop ↔ client subprocess contract | Accepted |
| [0005](0005-protocol-versioning.md) | Protocol versioning & capability negotiation | Accepted |
| [0007](0007-content-addressed-storage.md) | SHA-256 integrity verification and idempotent upload | Accepted |
| [0008](0008-client-accounts.md) | Client accounts, roles and bucket membership | Accepted |
| [0009](0009-rest-websocket-transport.md) | REST for data, WebSocket for events | Accepted |
| [0010](0010-zstandard-compression.md) | Zstandard compression with adaptive thresholds | Accepted |
| [0011](0011-resumable-upload.md) | Resumable uploads with atomic commit | Accepted |
| [0012](0012-rate-limiting.md) | Tiered per-IP rate limiting | Accepted |
| [0013](0013-hsyncignore-gitignore-syntax.md) | `.hsyncignore` using gitignore syntax | Accepted |
| [0014](0014-multi-repo-strategy.md) | Multi-repository architecture | Accepted |
| [0015](0015-mass-deletion-guard.md) | Mass-deletion safety guard | Accepted |
| [0016](0016-delta-transfer.md) | Delta transfer (rsync-style block sync) | Accepted |
| [0017](0017-lan-slave-outbound-event-reliability.md) | LAN slave outbound event reliability (defer-to-close uploads, echo-pair rename caching) | Accepted (uses the origin-based log labels of [ADR-0018](0018-origin-based-log-labels.md)) |
| [0018](0018-origin-based-log-labels.md) | Origin-based log labels (`LOCAL ` / `REMOTE `) with unified verbs | Accepted |
| [0020](0020-lan-security-model.md) | LAN security model: TOFU pinning, LAN key, and strict pairing | Accepted (unauthenticated-write policy superseded by [ADR-0029](0029-explicit-opt-in-unauthenticated-lan-writes.md)) |
| [0022](0022-causal-vector-clock-conflict-model.md) | Causal vector-clock conflict model | Accepted (tie-break defined by [ADR-0023](0023-corrected-mtime-tie-break.md)) |
| [0023](0023-corrected-mtime-tie-break.md) | Corrected-mtime chronological tie-break | Accepted |
| [0024](0024-capability-negotiation.md) | Capability negotiation (registry, channels, intersection) | Accepted |
| [0025](0025-sqlite-external-state-store.md) | SQLite external state store (folder UUID + ``syncstate.db``) | Accepted |
| [0026](0026-permission-special-bits-policy.md) | Special permission bits (setuid/setgid/sticky) policy | Accepted |
| [0027](0027-lan-leadership-lease.md) | LAN leadership lease: bounded incumbency and immediate yield | Accepted |
| [0028](0028-lan-peer-assisted-download.md) | LAN peer-assisted download | Accepted (eligibility/admission superseded in part by [ADR-0030](0030-lan-seeder-capacity-advertisement.md)) |
| [0029](0029-explicit-opt-in-unauthenticated-lan-writes.md) | Explicit opt-in for unauthenticated LAN writes | Accepted |
| [0030](0030-lan-seeder-capacity-advertisement.md) | LAN seeder capacity advertisement and requester admission | Accepted |
| [0031](0031-lan-peer-offload-lane-cost-reduction.md) | LAN peer-offload lane cost reduction (Phase 0 attribution) | Proposed |

## Related documents

- [HSYNC Common Architecture](../architecture.md)
- [LAN Discovery & Master Election](../../lan-protocol.md)
