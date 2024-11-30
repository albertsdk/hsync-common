# ADR 0017 — LAN slave outbound event reliability

- **Status:** Accepted
- **Date:** 2026-08-04

## Context

A LAN slave pushes local filesystem changes (create/modify/rename/delete) to the
elected master over HTTPS REST, including its own CID so the master can suppress
the echo broadcast. Two defects were observed on the slave → master path, both
rooted in the slave echoing its **own** locally-applied changes back to the
master, and in the inability to reliably distinguish an echo from a genuine new
event at the point where the decision must be made:

1. **Duplicate uploads on file creation.** On Linux both `on_created`
   (`IN_CREATE`) and `on_closed` (`IN_CLOSE_WRITE`) fire for a single
   `open(O_CREAT)+write+close`. The slave uploaded immediately in `on_created`
   for any non-empty file (the fast-path for files that arrive already complete
   with no subsequent close), and again in `on_closed` — two `[CLIENT UP]` /
   `[UPLOAD]` pairs for one creation, with no coordination between the handlers.
   Worse, the `on_created` fast-path used the conservative stability poll
   (`from_closed=False`), which can falsely declare a *write-pause-write* file
   stable during a pause and upload **half-written content**.

2. **Spurious rename 404.** A rename applied locally for an inbound master
   event is re-sent to the master by the slave's own watchdog (the
   `is_receiving` echo guard loses the race past the `_unmark` in the
   dispatch `finally`). The master answers `404` (source already renamed
   there) and the slave logged it as a `WARNING`, masking whether it was a
   benign echo or a real divergence (source genuinely missing on master).

The deciding constraint, stated explicitly: **never lose data, even at the cost
of redundant events.** A redundant upload is idempotent on the master (same
SHA-256 → no-op or harmless overwrite); a suppressed event is recoverable only
by the periodic resync.

## Decision

We adopt a single principle for slave → master outbound deduplication —
**reliability over economy**: never suppress an event unless it is *provably*
redundant; when the echo/genuine distinction cannot be made safely, send. Two
concrete mechanisms implement it, mirrored across the Python and Android
clients.

### 1. Defer-to-close uploads (create-upload deferral)

`on_created` for a non-empty regular file **no longer uploads immediately**. It
schedules a short daemon `Timer` (`CREATE_UPLOAD_DEFER_S`, equal to
`STABILITY_DELAY_ON_CLOSED`, ~300 ms). `on_closed` (`IN_CLOSE_WRITE`) — the
reliable trigger, since the writer fd is closed so the content is guaranteed
complete — **cancels the timer and takes precedence**, uploading with
`from_closed=True` (fast stability re-check). If `on_closed` never arrives
(atomic rename from outside the watch tree, hard-link, `mv` from a sibling
directory — no writer fd to close), the timer **fires as a fallback** and
uploads the already-complete file via the conservative poll. `on_deleted`,
`on_moved(src)` and shutdown cancel pending timers so a stale upload never
fires for a moved/deleted file.

This makes the reliable `from_closed=True` path win whenever it exists, while
preserving the fast-path that exists precisely because `on_created` cannot know
whether a `on_closed` will follow.

### 2. Echo-pair rename caching (404 disambiguation)

The slave records the exact `(src, dst)` pair of every rename it applies locally
for an inbound master event (short TTL). A `404` on a re-sent rename that
**matches** a recent inbound pair is degraded to `DEBUG` (benign echo — the
master already performed this same rename). A `404` with **no match** stays
`WARNING` (real divergence — source genuinely missing on master). The
exact-pair key is essential: a genuine user rename that reuses one of the paths
has a *different* pair and is never misclassified as an echo.

### Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| **Suppression guard (option A): first upload wins, `on_closed` suppressed** | Suppression is the risky operation for data integrity. A suppressed `on_closed` can carry the only reliable (fd-closed) view of a write-pause-write file; its content is lost until the periodic resync. The guard key (`path`) also collides on delete+recreate at the same path. |
| **Remove the `on_created` fast-path on Linux** | Regression for atomic-rename / hard-link / `mv`-in, which never emit `IN_CLOSE_WRITE`; those files would not upload until the resync. At `on_created` time you cannot know whether `on_closed` will follow, so you cannot safely drop the fast-path. |
| **Treat all rename `404`s as benign** | Hides genuine divergences (source genuinely missing on master) behind a benign log; the slave would never surface a real desync. |
| **Single-path TTL key for rename echo** | A user rename reusing one path of an inbound rename would match and be suppressed; only exact `(src,dst)` pair matching is safe. |

## Consequences

### Benefits

- **No duplicate uploads** for the common `open+write+close` case: a single
  upload via the reliable `on_closed` trigger.
- **No half-written-file uploads**: when `on_closed` exists, the upload runs
  only after the fd is closed and content is complete.
- **Atomic-rename / hard-link still upload** via the timer fallback (no
  `on_closed` expected).
- **Spurious `404` `WARNING` on rename echo eliminated**; real divergences
  still surface as `WARNING`.
- **Uniform principle across clients**: Python (`lan_websocket.py`) and Android
  (`LanSync.kt` + `InboundRenameEchoTracker.kt`) share the exact-pair cache and
  the defer-to-close behaviour.

### Costs and limits

- **Redundant uploads are possible in rare races** — e.g. the timer fires just
  as `on_closed` arrives, or a modification lands during a long upload. Both
  converge on the final content via the stability check and the master's
  last-write-wins semantics (ADR 0006); redundant network traffic is the
  accepted cost of the "never suppress" principle.
- **~300 ms added latency** for atomic-rename uploads (the defer window).
  Negligible versus transfer time and bounded.
- **State to manage**: a create-timer dict (lock + shutdown cleanup) and an
  echo-pair cache (TTL eviction). Both are small and session-bounded.
- **Modification-during-long-upload is not fully solved**: a stale upload could
  complete after a newer one. The periodic resync remains the safety net,
  consistent with the master-authoritative model (ADR 0006).

### Follow-up obligations

- Both clients must mirror the behaviour (Python `hsync_client/lan_websocket.py`
  `LANSlaveFileEventHandler`; Android `LanSync.kt` + `InboundRenameEchoTracker.kt`).
- Tests must cover: echo match / wrong-pair / expiry; `404` echo vs divergence;
  create defer / cancel-on-close / fire-on-no-close; cancel on delete/moved.
- The `[CLIENT NEW]` log label semantics changed from "complete on create"
  to "deferred to on_closed"; the log legend must reflect it if it documents
  that label.

## References

- [ADR 0006 — Master-authoritative conflict model](0006-master-authoritative-conflict-model.md) (last-write-wins on master)
- [ADR 0001 — Two sync modes: central server vs LAN P2P](0001-server-vs-lan-modes.md)
- Implementation: `hsync-client/hsync_client/lan_websocket.py` (`LANSlaveFileEventHandler`),
  `hsync-android/app/src/main/java/com/hsync/android/p2p/LanSync.kt` and
  `InboundRenameEchoTracker.kt`
