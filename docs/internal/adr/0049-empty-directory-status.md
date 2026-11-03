# ADR 0049 — An empty directory reports its own sync status

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

A directory with no syncable content carries nothing to compare, so it travels as
an internal `.hsynckeep` sentinel: the client materialises one per empty
directory (`sync.ensure_hsynckeep_files`) and the sentinel is the entry the engine
moves. Every consumer treats it as internal, never user content — the desktop
file panel excludes it from the scan, the preview drops its plan action, a
transfer event naming it is discarded, the serving pass skips its identity.

A front-end renders one row per entry, and a directory row carries the verdict
the engine reports for it. `dir_created` names a directory the engine materialises
from a live remote event; a directory the sentinel alone represents has no such
event, so its row has no verdict to render.

## Decision

The client reports the directory itself. `UiEventName.dir_status` carries `path`
(the directory, without the sentinel and without a trailing slash) and `state`
(`synced`, `to_upload`, `to_download`, `to_delete`). It is emitted by:

* the preview (`preview.py::_emit_empty_dir_status`), for every plan action that
  concerns a sentinel, so a front-end settles a directory that is already in sync
  (no transfer ever names it);
* the serving-side status pass (`master_status.py::_dir_states`), so a peer sees
  the directory’s verdict from the device that serves the share;
* the desktop engine (`engine/process.py::HsyncEngine._handle_transfer`), which
  turns a sentinel upload/download into the directory’s `synced` state.

A consumer renders the directory row from it and does not count it as a file: it
is a directory, and the sentinel stays out of every plan counter.

## Consequences

### Benefits

- An empty directory shows the truth — synced, to upload/download, or to delete —
  the same way a file does.
- The rule is uniform across front-ends: the client decides, the front-end renders.

### Costs and limits

- The event vocabulary carries one more name, and a consumer that ignores it
  renders the directory row from its own scan.
- The desktop keeps directory verdicts out of the file plan counters; a directory
  is not a file.

## References

- Wire contract: `hsync-common/hsync_common/protocol/events.py::UiEventName.dir_status`
- Producers: `hsync-client/hsync_client/preview.py::_emit_empty_dir_status`,
  `hsync-client/hsync_client/master_status.py::_dir_states`,
  `hsync-desktop/hsync_desktop/engine/process.py::HsyncEngine._handle_transfer`
- Consumer: `hsync-desktop/hsync_desktop/main_window/events.py::EventsMixin._on_directory_status`
