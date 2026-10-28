# ADR 0043 — The preview confirmation reports the plan

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

A sync plan reaches the user through a confirmation dialog: how many actions,
which ones, how much data and how long it will take. Most of it is derivable from
the per-file event stream (`file_status` carries path and size, `rename_status`
carries both paths), but two facts are not:

* **deletions the configured policy drops.** With `keep`, the client never emits
  a `to_delete` row, so a front-end sees the same stream as a run with nothing to
  delete. "Nothing to delete" and "deletions kept" are different answers, and one
  of them the user must be able to verify before confirming.
* **a plan the mass-deletion guard pauses.** The guard decides per cycle over the
  *unconfirmed* deletions only (a tombstone proves the removal is intentional).
  A confirmation that promised the wipe would be wrong about the run it describes.

## Decision

`preview_skipped` (`reason="deletion_policy"`, `count`, `size`) and
`preview_warning` (`reason="mass_delete_guard"`, `deletes`, `local`) are emitted
inside the preview cycle, before the per-file rows. A front-end states both, and
never infers them from the absence of a row.

The estimate is the front-end's job and uses the configured bandwidth limit per
direction (`MAX_BANDWIDTH_UPLOAD` / `MAX_BANDWIDTH_DOWNLOAD`). With no limit, no
number is shown: an invented rate would be worse than no estimate. Delta
transfer can move fewer bytes than the plan's sizes, so the value is presented as
approximate.

The plan's detail lists stay front-end-side and bounded (paths and sizes), because
a share can hold 100k files: the confirmation names every destructive action up to
a cap plus "and N more", and only the largest transfers. Counts and totals are
always exact.

## Consequences

### Benefits

- The dialog never claims a deletion that will be kept, nor a wipe that the guard
  will pause.
- The estimate has a stated basis, or is absent.
- A destructive plan is named file by file before the user confirms it.

### Costs and limits

- The event vocabulary grew by two preview-only names; a consumer that ignores
  them shows a plan without the policy/guard context (still correct, less informative).
- The detail lists bound what a single confirmation can name; the full plan stays
  visible in the file table.

## References

- Wire contract: `hsync-common/hsync_common/protocol/events.py::UiEventName.preview_skipped`
- Producer: `hsync-client/hsync_client/preview.py::_run_preview`
- Consumer: `hsync-desktop/hsync_desktop/preview_summary_dialog.py::PreviewSummaryDialog`
