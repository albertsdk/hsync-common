# ADR 0041 — Serving-side status-pass events

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

The `--events-json-fd` stream carries the per-file verdicts a front-end renders
(`file_status`, `rename_status`). A front-end also has to know when such a burst
is complete: without an explicit end it can only guess from a quiet period, which
makes an in-progress comparison indistinguishable from a stalled one and settles a
summary on partial data.

The same burst is produced by two roles with different meanings:

- a **secondary** node answers the front-end's `PREVIEW` command with the preview
  it then asks to confirm (a `SYNC` command follows an accepted summary);
- the **serving** device (p2p primary) compares the share it holds with the
  inventories the devices published, on every inventory change and on `PREVIEW`.
  It is the source of the share, so there is nothing for it to pull and no sync to
  confirm.

One pair of markers cannot describe both: a serving pass that reused the preview
pair consumed the confirmation of the preview the front-end was waiting for, which
then showed a summary built from the classification's counters and never sent the
`SYNC` that ends its dry run. The quiet-period workaround that replaced it left
the front-end unable to distinguish "a pass ran" from "a pass is stuck", and the
per-file counters of a serving device accumulated across passes because nothing
marked a pass boundary.

## Decision

A comparison burst is always bracketed by an explicit marker pair, and the pair
identifies **who** asked for the comparison:

| Pair | Producer | Meaning for a front-end |
| --- | --- | --- |
| `preview_start` / `preview_end` | the client answering the front-end's `PREVIEW` on a requester path | the preview this front-end requested; only its end may confirm a pending sync |
| `status_pass_start` / `status_pass_end` | the serving role (`MasterSyncStatus.run_now`) | a classification pass of the share this device serves; render it, never confirm a sync |

The names are SSOT in `hsync_common/protocol/events.py::UiEventName`. Every
`file_status` / `rename_status` burst is bracketed by exactly one of the pairs,
whatever the outcome — including the branches that can only answer
`sync_pending` (no device, or a device that published no inventory yet).
Consumers reset their per-comparison counters on a start marker and render the
summary on an end marker; quiet-period inference is not part of the contract.

## Consequences

### Benefits

- One invariant instead of two heuristics: a consumer always knows when a burst
  ended, and a stalled pass stays visibly in progress.
- The confirmation state of a requested preview can only be consumed by
  `preview_end` — by construction, not by a role guard in the consumer.
- Per-comparison counters stay exact: a serving device's repeated passes no
  longer accumulate into an inflated summary.
- A front-end can offer the same "compare now" action in both roles: on a
  secondary node it ends with the sync confirmation, on a primary with the
  refreshed rows and file-set state.

### Costs and limits

- The event contract grew by two names; every consumer of the stream must know
  them (the desktop today).
- Both producers must keep the brackets complete, including on the early-return
  branches, or a front-end stays in its in-progress state.
- A serving pass reports no `to_delete` / `to_rename`: it compares the identities
  the devices hold, so deletions and renames on the served share are not part of
  its classification output.

## References

- Wire contract: `hsync-common/hsync_common/protocol/events.py::UiEventName`
- Serving-side producer: `hsync-client/hsync_client/master_status.py::MasterSyncStatus.run_now`,
  dispatched by `hsync-client/hsync_client/p2p_handler.py::_MasterChannel`
- Requester-side producer: `hsync-client/hsync_client/preview.py::_run_preview`
- Desktop consumer: `hsync-desktop/hsync_desktop/engine/process.py::HsyncEngine` →
  `hsync-desktop/hsync_desktop/main_window/events.py::EventsMixin._on_status_pass_ended`
