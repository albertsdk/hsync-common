# ADR 0005 — Protocol versioning & capability negotiation

- **Status:** Accepted
- **Date:** 2026-06-21

## Context

HSYNC has multiple wire channels (REST, WebSocket, LAN/TXT) shared by a server
and three clients (Python, desktop, Android). Originally the *app* version
doubled as the *protocol* version, so a cosmetic app bump implied a protocol
change, and compatibility was checked with fuzzy "is this version new enough?"
logic. With independent repos this invites silent drift and ambiguous failures.
There is **no legacy install base** to keep working.

## Decision

We will separate the **protocol version from the semantic app version** and make
capabilities explicit, with a single source of truth in
`hsync_common.protocol.handshake`:

- Per-channel constants `PROTOCOL_VERSION_REST = "api/1"`,
  `PROTOCOL_VERSION_WS = "ws/1"`, `PROTOCOL_VERSION_LAN = "lan/1"`, bumped only on
  a breaking change to *that* channel's wire shape.
- A mismatched `protocol_version` is a **hard failure** (REST → 426, WS →
  handshake closed, LAN → peer ignored), never a negotiation.
- A `Capability` registry (`compression`, `tombstones`, `never_master`,
  `https`, `delta`, `vector_clocks`) carried on the handshake channels as
  **feature flags within the same protocol version** — unknown tokens are
  dropped, never treated as a version conflict.
- All sides build/parse handshakes via the shared `build_*`/`parse_*` helpers;
  Android mirrors them in `Protocol.kt` and validates against golden fixtures.

## Consequences

- Channels evolve independently; a breaking change forces an explicit version
  bump and an immediate, legible failure instead of subtle misbehaviour.
- Optional features are advertised and detected uniformly, which the desktop
  reuses to gate its UI ([ADR-0004](0004-desktop-subprocess-contract.md)).
- The capabilities document for the CLI/desktop builds on these same constants,
  so protocol versions and feature flags have one origin.
- `vector_clocks` advertises causal version metadata support
  ([ADR-0022](0022-causal-vector-clock-conflict-model.md)): when absent, a peer
  simply sends no version metadata and the receiver treats it as an empty clock
  — never an error.
