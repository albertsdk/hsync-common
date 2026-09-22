# ADR 0032 — Bootnode discovery (`boot/1`)

- **Status:** Accepted (its "never imports `hsync-common`" clause is superseded by [ADR-0033](0033-bootnode-python-reuses-hsync-common.md))
- **Date:** 2026-10-09

## Context

The peer data-plane (`p2p/1`, ADR-0002/0020) discovers peers over mDNS, which
only works when the nodes share a local network. Reaching peers across
networks (NAT, distinct sites) needs a rendezvous point that both nodes can
reach: a lightweight, no-log bootstrap node that relays a random sample of
peers for a bucket. The bootstrap channel is a new wire contract with its own
lifecycle, so it needs its own version and specification.

`hsync-common` is the SSOT for the data-plane protocol, but the bootnode is a
standalone daemon (and a future Rust port) that must not depend on this
package. At the same time the `hsync-client` needs typed access to the
bootstrap frames to speak to the node.

## Decision

We will introduce the `boot/1` bootstrap protocol, specified canonically in
`hsync-bootnode/protocol-spec/boot-1.md` with canonical golden fixtures in
`hsync-bootnode/fixtures/`. The bootnode daemon keeps its own Python model of
the frames and never imports `hsync-common`.

`hsync-common` carries a **mirror** of the contract in
`hsync_common/protocol/bootnode.py` (frame models, `PROTOCOL_VERSION_BOOT`,
`BOOT_ALPN`, the bucket-token helpers) plus a byte-identical copy of the
golden fixtures. A drift test (`tests/test_protocol_bootnode.py`) compares the
mirror against the canonical `hsync-bootnode/fixtures/`, so the two copies
cannot diverge silently. The mirror is the single source for the client; the
bootnode fixtures remain the source for every implementation.

Two fields are defined as follows:

- **`capacity`** is an **advisory service-capacity hint** (`0..32`, `0` = not a
  peer-download seeder), copied from `register` onto the peer record and
  relayed in every `query` peer. It is **not authenticated and not
  authoritative**: the requester may use it only to pre-size concurrency and to
  skip `capacity=0` peers, never to exclude a live seeder. The authoritative
  value stays `serve_slots` on the authenticated data-plane handshake
  (ADR-0030); the sample is never ordered by it, so a self-declared value buys
  no priority.
- **`reachable`** is derived from `bool(endpoints)` at `register` time: a peer
  is advertised as reachable only if it published at least one listen endpoint.
  A register with no endpoint (the first STUN register) is advertised with
  `reachable=false` and its observed UDP source as the fallback endpoint;
  `refresh` never changes it.

The bootstrap document is advertised in `--capabilities-json` as
`protocol_version.boot` (capabilities schema v3), alongside `rest`, `ws` and
`p2p`.

## Consequences

- Cross-network discovery becomes possible without coupling the bootnode to
  `hsync-common` or to a specific implementation language; the fixtures are the
  cross-language contract.
- The mirror adds a duplicated frame definition to `hsync-common`; the drift
  test is what keeps the duplication safe. The mirror stays dependency-free
  (`TypedDict` + hand-written strict validators that reject unknown fields, the
  same acceptance as the bootnode's `extra="forbid"` models), so it adds no
  pydantic dependency to `hsync-common`; the duplicated validators are the cost.
- The bootstrap hint is deliberately non-authoritative, so a stale or spoofed
  `capacity` can at worst cause a failed attempt followed by the mandatory
  master fallback — it can never exclude a live seeder.
- `hsync-client` gains a `p2p` mode that uses the bootnode as an optional
  discovery source; the bootnode remains optional (mDNS-only operation stays
  valid).
