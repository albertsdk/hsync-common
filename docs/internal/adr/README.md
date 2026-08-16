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
| [0006](0006-master-authoritative-conflict-model.md) | Master-authoritative conflict model | Superseded by [ADR-0022](0022-causal-vector-clock-conflict-model.md) |
| [0007](0007-content-addressed-storage.md) | SHA-256 integrity verification and idempotent upload | Accepted |
| [0008](0008-single-api-key-auth.md) | Single shared API key authentication | Accepted |
| [0009](0009-rest-websocket-transport.md) | REST for data, WebSocket for events | Accepted |
| [0010](0010-zstandard-compression.md) | Zstandard compression with adaptive thresholds | Accepted |
| [0011](0011-resumable-upload.md) | Resumable uploads with atomic commit | Accepted |
| [0012](0012-rate-limiting.md) | Tiered per-IP rate limiting | Accepted |
| [0013](0013-hsyncignore-gitignore-syntax.md) | `.hsyncignore` using gitignore syntax | Accepted |
| [0014](0014-multi-repo-strategy.md) | Multi-repository architecture | Accepted |
| [0015](0015-mass-deletion-guard.md) | Mass-deletion safety guard | Accepted |
| [0016](0016-delta-transfer.md) | Delta transfer (rsync-style block sync) | Accepted |
| [0017](0017-lan-slave-outbound-event-reliability.md) | LAN slave outbound event reliability (defer-to-close uploads, echo-pair rename caching) | Accepted (*terminology superseded by [ADR-0018](0018-origin-based-log-labels.md); algorithm still valid*) |
| [0018](0018-origin-based-log-labels.md) | Origin-based log labels (`LOCAL ` / `REMOTE `) with unified verbs | Accepted |
| [0020](0020-lan-security-model.md) | LAN security model: TOFU pinning, LAN key, and strict pairing | Accepted |
| [0022](0022-causal-vector-clock-conflict-model.md) | Causal vector-clock conflict model | Accepted (tie-break amended by ADR-0023) |
| [0023](0023-corrected-mtime-tie-break.md) | Corrected-mtime chronological tie-break | Accepted |

## Related documents

- [HSYNC Common Architecture](../architecture.md)
- [LAN Discovery & Master Election](../../lan-protocol.md)
