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
- While the ecosystem is pre-release, ADRs describe the **current design** as if
  it had always been this way: they carry no superseded clauses, no
  "previously / renamed / removed" history, and no references to retired options
  or module names. Once the ecosystem is published, the records become
  **append-only**: a changed decision is then recorded as a new ADR that marks
  the old one *Superseded by* it.
- Status values: `Proposed`, `Accepted`, `Superseded`.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-server-vs-p2p-modes.md) | Two sync modes: central server vs p2p | Accepted |
| [0002](0002-p2p-master-election.md) | Deterministic p2p master election | Accepted |
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
| [0017](0017-p2p-slave-outbound-event-reliability.md) | p2p slave outbound event reliability (defer-to-close uploads, echo-pair rename caching) | Accepted |
| [0018](0018-origin-based-log-labels.md) | Origin-based log labels (`LOCAL ` / `REMOTE `) with unified verbs | Accepted |
| [0020](0020-p2p-security-model.md) | p2p security model: TOFU pinning, p2p key, and strict pairing | Accepted |
| [0022](0022-causal-vector-clock-conflict-model.md) | Causal vector-clock conflict model | Accepted |
| [0023](0023-corrected-mtime-tie-break.md) | Corrected-mtime chronological tie-break | Accepted |
| [0024](0024-capability-negotiation.md) | Capability negotiation (registry, channels, intersection) | Accepted |
| [0025](0025-sqlite-external-state-store.md) | SQLite external state store (folder UUID, per-folder / per-bucket DBs) | Accepted |
| [0026](0026-permission-special-bits-policy.md) | Special permission bits (setuid/setgid/sticky) policy | Accepted |
| [0027](0027-p2p-leadership-lease.md) | p2p leadership lease: bounded incumbency and immediate yield | Accepted |
| [0028](0028-p2p-peer-assisted-download.md) | p2p peer-assisted download | Accepted |
| [0029](0029-explicit-opt-in-unauthenticated-p2p-writes.md) | Explicit opt-in for unauthenticated p2p writes | Accepted |
| [0030](0030-p2p-seeder-capacity-advertisement.md) | p2p seeder capacity advertisement and requester admission | Accepted |
| [0031](0031-p2p-peer-offload-lane-cost.md) | p2p peer-offload lane cost: attribution and accepted trade-off | Accepted |
| [0032](0032-bootnode-discovery.md) | Bootnode discovery (`boot/1`) and the hsync-common mirror | Accepted |
| [0033](0033-bootnode-python-reuses-hsync-common.md) | The bootnode Python v1 reuses hsync-common utilities | Accepted |
| [0034](0034-bootnode-tls-trust.md) | Bootnode TLS trust: fingerprint pinning and opt-in TOFU | Accepted |
| [0035](0035-bootnode-trust-policy.md) | Bootnode trust policy: SSH-like `ask` and `known_hosts` | Accepted |
| [0036](0036-server-tls-trust-unification.md) | Unified SSH-style TLS trust for the sync server (`chain`, `hsync trust`) | Accepted |
| [0037](0037-shared-service-identity-model.md) | Shared self-signed service identity model (ECDSA, unencrypted key, 20-year validity) | Accepted |
| [0038](0038-bootnode-endpoint-candidate-list.md) | Bootnode relays the full endpoint candidate list | Accepted |
| [0039](0039-combined-discovery.md) | Combined mDNS and bootnode discovery | Accepted |
| [0040](0040-p2p-master-trust-policy.md) | P2P master trust policy: `ask` by default | Accepted |
| [0041](0041-serving-side-status-pass-events.md) | Serving-side status-pass events: two comparison marker pairs | Accepted |

## Related documents

- [HSYNC Common Architecture](../architecture.md)
- [p2p Discovery & Master Election](../../p2p-protocol.md)
