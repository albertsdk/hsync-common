# ADR 0024 — Capability negotiation (registry, channels, intersection)

- **Status:** Accepted
- **Date:** 2026-08-16

## Context

Every HSYNC component shares a capability registry (`Capability` in
`hsync_common.protocol.handshake`) and the desktop/client have a
process-boundary capabilities document (`--capabilities-json`, ADR-0004).
Exactly **where, when, and which** capability set travels on each channel must
be codified once, and the advertising must be honest: a feature is announced
only when it is actually implemented and enabled.

## Decision

We will define one coherent capability-negotiation policy across every channel:

1. **`hsync-common` stays the single source of truth** for the registry, the
   per-channel versions, and the LAN master⇄slave handshake frames
   (`build_lan_auth_required`, `build_lan_auth`, `build_lan_auth_ok`,
   `build_lan_auth_failed`, `build_lan_hello` with dedicated TypedDicts). A
   LAN WSS handshake JSON Schema (`lan/wss-schema.json`) and golden fixtures
   pin these frames cross-language.
2. **Every frame of the LAN master⇄slave WSS handshake carries
   `protocol_version` and `capabilities`.** A mismatch is a hard failure
   (peer refused), exactly like the WS channel. Hello frames exchange
   capabilities for coherence only — without a `LAN_KEY` they are **not
   authenticated** and are logged, never trusted.
3. **The authenticated transport is the authoritative capability source.**
   The slave adopts the master's capabilities from the auth reply into the
   transfer gates (`SERVER_COMPRESSION_ENABLED` / `SERVER_DELTA_ENABLED`). The
   TXT record is a discovery-time hint only.
4. **Intersection semantics, never negotiation**: a feature is used only when
   both sides advertise it; an absent capability degrades the feature (delta →
   full transfer, compression → raw, no clocks → empty clock), never an error.
   Unknown tokens stay silently ignored.
5. **Honest advertising per channel**: the TXT record and the handshakes
   announce what is actually implemented and enabled. `compression` and `delta`
   are advertised on the TXT record only when enabled. Causal version metadata
   (`vector_clocks`) and deletion gossip (`tombstones`) are hard dependencies of
   the conflict/deletion model (ADR-0022/0003), so every build supports them;
   they are negotiated on the authenticated handshake only and carry no
   information on the unauthenticated TXT record, which does not advertise them.
   The central-server auth reply and the LAN handshake use the same
   runtime-derived set (`hsync_client.capabilities.local_capabilities`).
6. **The desktop `CapabilitiesDoc` is NOT a wire mechanism**: it crosses a
   process boundary (binary → GUI) and carries `cli_options`; it is not extended
   into the network handshakes.

Alternatives rejected: negotiating across protocol versions (contradicts
ADR-0005 — versions hard-fail, only capabilities are flags); trusting the TXT
record at connection time (it is unauthenticated and staleable — the security
model treats discovery data as "hint, never proof").

## Consequences

- The LAN handshake, its schema and its fixtures are part of the committed
  contract (`--check` gates drift); Android mirrors the frames in `Protocol.kt`
  and is pinned by the parity fixtures.
- A fresh, authenticated capability snapshot exists at connection time on the
  LAN; a TXT/handshake inconsistency is observable in logs instead of silently
  mis-gating features.
- Future capabilities must follow one pattern: add the token to the registry,
  advertise it in `local_capabilities()` (Python) and the Kotlin equivalent,
  document the channel in `lan-protocol.md`, and regenerate schemas/fixtures.
