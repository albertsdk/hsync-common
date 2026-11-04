# ADR 0049 — An empty directory reports its own sync status

- **Status:** Accepted
- **Date:** 2026-11-03

## Context

A directory with no syncable content carries nothing to compare, so it travels as
an internal `.hsynckeep` sentinel: the client materialises one per empty
directory (`sync.ensure_hsynckeep_files`) and the sentinel is the entry the engine
moves. Every consumer treats it as internal, never user content — the desktop
file panel excludes it from the scan, the plan never names it, the serving pass
keeps it out of the per-device backlog, and the sync-set totals skip it.

A front-end renders one row per entry, and a directory row carries the verdict
the engine reports for it. `dir_created` names a directory the engine materialises
from a live remote event; a directory the sentinel alone represents has no such
event, so its row has no verdict to render.

## Decision

The client reports the directory itself. `UiEventName.dir_status` carries `path`
(the directory, without the sentinel and without a trailing slash) and `state`
(`synced`, `to_upload`, `to_download`, `to_delete`). The verdict is derived from
the sentinel identity the peer side holds, so it settles a directory already in
sync, which no transfer ever names:

* the preview (`preview.py::_run_preview`, via `empty_dirs.empty_dir_states`
  driven by the local and remote listings) emits it for the comparison a
  front-end requests;
* the serving-side status pass (`master_status.py::_classify`, via
  `empty_dirs.empty_dir_states` driven by the published inventories) emits it for
  the device that serves the share.

`empty_dirs` is the single source of the rule: `synced` when the peers hold the
sentinel identity, `to_upload` when nobody does, `to_download` for a sentinel
only the peers hold. A consumer renders the directory row from it and does not
count it as a file: it is a directory, and the sentinel stays out of every plan
counter and every per-device backlog.

## Consequences

### Benefits

- An empty directory shows the truth — synced, to upload/download, or to delete —
  the same way a file does, and the same on every device.
- The rule is uniform across front-ends: the client decides, the front-end renders.

### Costs and limits

- The event vocabulary carries one more name, and a consumer that ignores it
  renders the directory row from its own scan.
- The desktop keeps directory verdicts out of the file plan counters; a directory
  is not a file.

## References

- Wire contract: `hsync-common/hsync_common/protocol/events.py::UiEventName.dir_status`
- Rule: `hsync-client/hsync_client/empty_dirs.py`
- Producers: `hsync-client/hsync_client/preview.py::_run_preview`,
  `hsync-client/hsync_client/master_status.py::_classify`
- Consumer: `hsync-desktop/hsync_desktop/main_window/events.py::EventsMixin._on_directory_status`
