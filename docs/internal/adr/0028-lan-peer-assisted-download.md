# ADR 0028 — LAN peer-assisted download

- **Status:** Accepted
- **Date:** 2026-09-09

## Context

LAN synchronization currently moves every full-file download through the
elected master. The master must remain the tracker, causal arbiter, event hub,
and guaranteed source, but making it relay bytes already held by another slave
unnecessarily concentrates network and disk load. A peer-assisted path must not
give seeders write authority, weaken checksum verification, change election or
presence, or turn file transfer into multi-source chunking.

The capability must degrade safely for mixed `lan/1` peers and for stale or
spoofed mDNS hints. Inventory publication also needs a bounded, sequenced
contract: exposing a partial snapshot, accepting an ambiguous retry, or trusting
an old connection after a CID reconnect would make source answers incorrect.

## Decision

We will add peer-assisted **full regular-file downloads** to LAN mode with these
boundaries:

1. The master remains tracker, causal arbiter, event relay, and guaranteed
   download fallback. Uploads, deletes, renames, permission changes, tombstone
   mutation, and delta transfer remain master-coordinated. Delta-to-master is
   attempted before peer-assisted full transfer.
2. Peer download is enabled by default (`HSYNC_LAN_PEER_DOWNLOAD`) and may be
   disabled explicitly (`--no-peer-download`). Source lookup applies only at or
   above `HSYNC_LAN_PEER_DOWNLOAD_MIN_SIZE` (1 MiB by default; zero means all
   sizes). A requester tries at most `HSYNC_LAN_PEER_SOURCES_MAX` unique peer
   CIDs per file (default 3, valid range 1–8). Missing support and every peer
   failure remain a transparent master fallback.
3. Continuous, non-dry-run slaves may bind a read-only HTTPS seeder and publish
   an inventory to the master. One-shot clients may request peer sources but do
   not seed or publish. Inventory and serving contain regular files only. Seeder
   response-body concurrency (`HSYNC_LAN_PEER_READ_CAP`) defaults to two and is
   configurable only in the bounded range 1–32; saturation returns 503 before
   the file is opened.
4. `Capability.peer_download` means a node implements inventory, batch source
   lookup, and seeder semantics. A master advertises optional TXT
   `peer_download=true` when its source endpoint is available; a slave advertises
   optional `seed=true` only while its seeder is successfully bound. A serving
   master or seeder also publishes `https` and `cert_fp` endpoint material.
5. We will keep `lan/1`. The WSS capability is authoritative after an
   authenticated handshake; TXT and no-key hello values are availability hints.
   Missing support or any peer-source failure degrades to master-only download.
6. Requesters batch at most 500 unique normalized paths in
   `POST /api/v1/buckets/{bucket}/files/sources`. Each response preserves the
   `(path, sha256)` identity and returns at most eight current peer candidates;
   the requester and master are omitted. The complete HTTPS download endpoint,
   candidate CID, fingerprint, and compression support are returned. Request and
   response objects are strict and bounded to 2 MiB at the transport. Candidates
   require exact indexed-hash membership, current session ownership, and current
   liveness. Ranking biases same-subnet peers first (IPv4 `/24`, IPv6 `/64`) and
   randomizes within each partition; proximity is never authority.
7. The master stores holder inventory in the role-local SQLite database
   `default_device_dir()/lan-index/<sha256(bucket UTF-8)>.sqlite3` (with an
   app-private equivalent on Android). Master activation transactionally clears
   crash leftovers and rebuilds state from publisher snapshots. Endpoint
   material is resolved from live discovery at lookup time rather than persisted
   in the index.
8. Seeder inventory uses additive WSS `inventory` and `inventory_ack` frames.
   Frames carry non-boolean signed-64-bit `gen`/`seq`, `snapshot|delta` mode,
   `more`, and at most 500 strict entries. Snapshots are staged and atomically
   replace a CID only at the terminal frame. Deltas are independent
   `more=false` transactions. ACK status is `ok|resync|rejected` and identifies
   both generation and sequence; rejected ACKs carry a bounded machine reason.
   Connection ownership, contiguous sequencing, canonical terminal-frame digests
   for idempotent retry, quotas, and staging expiry prevent stale sessions and
   unbounded publication. The bounds
   are 2,000,000 committed-plus-staged rows per CID, 20,000,000 rows globally,
   64 publisher sessions, and five minutes for staged snapshot expiry.
9. Every peer fetch is content-addressed by the requested `(path, sha256)`.
   Seeders require the expected lowercase hash and requester CID, serve through
   descriptor-safe regular-file reads, and return the canonical
   `X-Checksum-SHA256` header. The requester treats source metadata as untrusted
   corroboration and verifies the complete file against the listing hash before
   atomic replacement. Seeders expose only health, time, and exact-hash download
   reads; list, source, delta, tombstone, and mutation routes are unavailable.
10. Seeder identity uses TOFU certificate pinning. Strict pairing remains scoped
   to the elected master. Persisting a first-use seeder pin must succeed before
   transfer proceeds. Requesters use a fresh explicit pinned client per
   candidate, fixed 2-second connect and 30-second read timeouts, and no HTTP
   retry layer. They retain partial bytes only after an interrupted body and
   discard completed corrupt or range-inconsistent bodies before trying another
   peer or the master.
11. No new structured event names are introduced. A successful existing
   `transfer` event may include `source_cid` only when a peer supplied the fully
   verified full-file body; master and delta transfers omit it.

The independent authorization policy for mutation without a LAN key is defined
by [ADR-0029](0029-explicit-opt-in-unauthenticated-lan-writes.md), not by this
download decision.

## Consequences

- Large LAN downloads can use another exact-hash holder while preserving the
  master's authority and fallback availability.
- Mixed `lan/1` fleets remain interoperable through additive capability gates.
- The master gains a role-local SQLite holder index and sequencing/quota
  machinery; publishers gain snapshot/delta lifecycle and reconnect handling.
- Every slave seeder adds a read-only network surface, certificate pin, bounded
  concurrent-read cost, and descriptor-safe serving obligation.
- Source selection is an optimization only: stale discovery, missing inventory,
  TLS/pin failure, overload, content mismatch, or unsupported peers cannot make
  synchronization depend on a seeder.
