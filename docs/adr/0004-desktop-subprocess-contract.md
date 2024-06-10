# ADR 0004 — Desktop ↔ client subprocess contract

- **Status:** Accepted
- **Date:** 2026-06-22

## Context

The desktop GUI (`hsync-desktop`, PySide6) does not re-implement sync; it drives
the `hsync` client **as a subprocess**. Historically it inferred state by parsing
human-readable log lines with regular expressions and assumed the client
supported a fixed set of CLI flags. Both couplings are brittle: any reword of a
log message, or a binary built without a given feature, silently broke the UI or
exposed controls the binary could not honour.

## Decision

We will define an **explicit, versioned contract** between desktop and client,
replacing log scraping and hard-coded assumptions:

- **Structured events** — the client emits versioned JSON Lines on a dedicated
  channel (`--events-json-fd`) carrying `schema_version`; the desktop consumes
  *only* these events for state (`role_changed`, `transfer`, `sync_complete`,
  `pairing_needed`, …). The log-regex parser is removed.
- **Capability discovery** — the client prints a capabilities document via
  `--capabilities-json` (assembled by `hsync_common.protocol.capabilities`):
  supported CLI options, protocol versions, events schema version and feature
  flags. The desktop probes this at startup and **gates UI controls** on it,
  disabling and unchecking unsupported toggles (e.g. LAN options) rather than
  emitting flags the binary rejects.

## Consequences

- The UI is decoupled from log wording and from the binary's exact feature set:
  a reduced-capability binary degrades the UI gracefully instead of breaking.
- The CLI surface advertised by `--capabilities-json` is introspected from the
  real command, so it cannot drift from the actual interface.
- Desktop ↔ client compatibility becomes contract-testable against fixtures
  rather than against prose; an unknown event/capabilities `schema_version` is
  rejected explicitly.
- New client features are surfaced to the desktop by adding a capability/event,
  not by changing log strings — see [ADR-0005](0005-protocol-versioning.md).
