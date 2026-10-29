# ADR 0046 — One log-line grammar for every HSYNC producer

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

Every HSYNC component writes human-readable log lines, and they meet in one
place: the Desktop's **Log** panel, which renders the `hsync-client` engine's
stdout (launched with `--color=always`) next to the GUI's own status messages.
The client and the server already shared a renderer
(`hsync_common.logger.build_record_formatter`: timestamp, `[pid]`,
correlation field, level, message), but the Desktop — which has no loguru stack
at all — re-implemented the layout by string concatenation, and two other
Desktop modules re-encoded the grammar in regexes of their own (the level
coloring in `log_style` and the "last client errors" harvest in the engine).

That produced three drifts in the same panel:

1. the Desktop line carried a single bracket field (`[desktop]` in place of
   `[pid] [client_id]`), so a reader/parser written for the client skipped it;
2. the Desktop stamped its lines with `datetime.now()` — a naive **local** wall
   clock — while appending the UTC `Z` suffix the client uses, so Desktop lines
   read hours ahead of interleaved client lines (and the suffix was a lie);
3. some Desktop lines (`--- … ---` phase markers, the raw `[EVENT ERROR]`
   payload) bypassed the shape entirely, leaving lines with no timestamp and no
   level in the same stream.

## Decision

We will keep **one grammar** for every producer, whatever its sink:

```
<timestamp> - [<pid>] [<correlation field> …] LEVEL: message
```

- It is defined once, in `hsync_common.logger`: `LOG_LINE_RE` (parser),
  `format_log_line` (renderer for producers without loguru) and `LOG_LEVELS`
  (the level vocabulary, derived from `LEVEL_STYLES`), next to
  `build_record_formatter` which renders the same shape for the loguru sinks.
- The correlation fields identify the producer, not the layout: `[<client_id>]`
  for the client, `[<request_id>]` for the server, `[desktop]` for the GUI
  (which has no client session, so the Desktop renders its own pid first).
- Timestamps are **UTC** (`Z`) for every producer; a local clock must attach
  its zone instead of being labelled `Z`.
- Desktop phase markers and engine diagnostics are log records too: they are
  emitted through the same renderer (`_append_desktop_log`) as `INFO`/`ERROR`
  lines, never as prefix-less strings.

Rejected alternatives: keeping `[desktop]` as the only identity field (the
parser would still need two grammars, and the client's pid slot would stay
unusable for GUI lines); faking a client CID for the GUI (a fabricated
correlation id is worse than none); stripping `[pid] [cid]` from the client
lines to "meet in the middle" (loses session correlation the desktop relies on).

## Consequences

- The panel is uniform: one parser (`LOG_LINE_RE`) colors the level, harvests
  the client's last errors and reads both producers, so the consumers in
  `hsync-desktop` no longer encode the shape locally.
- Desktop timestamps now sort correctly against client lines (previously UTC+0
  labels on local times).
- `format_timestamp` routes through one `_render_timestamp`, so an aware
  instant is always converted to UTC before rendering.
- Follow-up obligations: new Desktop-originated lines must go through
  `main_window/ui.py::UiBuildMixin._append_desktop_log`; new levels are added to
  `LEVEL_STYLES` only (the vocabulary follows); the grammar is documented in
  `docs/log-labels.md` and covered by a cross-renderer test in
  `hsync-common/tests/test_logger.py`.
- `hsync-common` gains a public symbol (`format_log_line`, `LOG_LINE_RE`,
  `LOG_LEVELS`), so a package release must precede a Desktop release that calls
  them.
