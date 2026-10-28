# ADR 0042 — The serving-side sync status is per device

- **Status:** Accepted
- **Date:** 2026-10-28

## Context

A serving device (p2p primary) classifies the share it holds against what the
connected devices published. The published inventories are a set of
``(path, sha256)`` identities per device, and reading them as one union answers a
different question than the one a status bar asks:

* the union answers "does **any** device hold this?" — enough for the per-file
  verdicts (``synced`` / ``to_upload`` / ``to_download``);
* a status bar has to answer "is **every** device converged?", and the union
  cannot: a file only one device holds reads ``synced`` while the others still
  need it, and an aggregate pending count mixes devices with no attribution.

With a single device connected the two questions collapse, which is why the
union view is correct in the two-node case and misleading from three devices on.
A second, independent gap: an opened inventory session that has not committed its
snapshot yet is indistinguishable from an empty share, so a partial group could
produce a verdict nobody verified.

## Decision

A serving pass reports **one row per live device** and stamps every per-file row
with its coverage.

* ``device_status`` carries, per live device, ``held`` (identities it published),
  ``pending_here`` (its identities the share lacks) and ``pending_there`` (share
  identities it does not hold). It is emitted inside the
  ``status_pass_start``/``status_pass_end`` bracket, before the per-file rows.
* ``file_status`` carries ``holders`` and ``devices``: how many of the compared
  devices hold the identity. A row is plain *in sync* only when
  ``holders == devices``.
* ``sync_pending`` carries ``devices``/``expected``: a pass refuses to classify
  while a live session has no committed snapshot, so the front-end shows the
  waiting state with the count instead of a verdict on a partial group.

A front-end renders the **worst device** (largest ``pending_here +
pending_there``) in its aggregate and lists every device in the detail. With one
device the worst device is that device, so the rendering degenerates to the
single-device one.

The comparison is one pass over the holder table: the union, the per-identity
holder count and the per-device tallies come from the same read
(``P2PInventoryStore.compare_share``), never from a per-identity query.

## Consequences

### Benefits

- The aggregate answers the group question: "all in sync" means every device is.
- A lagging device is named with its own backlog instead of dissolving into a
  union count.
- Partial inventories can no longer produce a verdict; the waiting state carries
  how many devices published out of how many are connected.
- Per-row coverage keeps the table honest without a new column (a numeric
  suffix, language-neutral).

### Costs and limits

- The wire grows by one event per device per pass and two integers per file row.
- The pass keeps one small integer per distinct identity (the per-identity holder
  count); the per-device tallies stay O(devices).
- A serving pass still has no ``to_delete``/``to_rename`` verdict: it compares
  identities the devices hold, not the intent to delete.

## References

- Wire contract: `hsync-common/hsync_common/protocol/events.py::UiEventName.device_status`
- Producer: `hsync-client/hsync_client/master_status.py::MasterSyncStatus._classify`
  over `hsync-client/hsync_client/p2p_inventory.py::P2PInventoryStore.compare_share`
- Consumer: `hsync-desktop/hsync_desktop/main_window/events.py::EventsMixin._serving_sync_state`
