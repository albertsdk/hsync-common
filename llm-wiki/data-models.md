# HSYNC Common Library — Data Models (`hsync_common/models/`)

Canonical sync types. All are plain dataclasses with a paired `TypedDict` for the
wire shape. Re-exported from `hsync_common/models/__init__.py:1`.

## Types

| Type | File:line | Wire dict | Notes |
| ---- | --------- | --------- | ----- |
| `File` | `models/file.py:178` | `FileDict` (`models/file.py:80`) | sync metadata + content hash |
| `Dir` | `models/dir.py:54` | — | `path`, octal `permissions` |
| `Symlink` | `models/symlink.py:14` | — | `filepath`, `target`, `name`, times |
| `Event` | `models/event.py:63` | `EventDict` (`models/event.py:34`) | FS change; `EventName` enum `models/event.py:44`; `is_valid_cid` wire validator `models/event.py:29` |
| `SyncAction` | `models/sync_action.py:31` | — | decision; `SyncActionName` enum `models/sync_action.py:14` |
| `TombstoneStore` | `models/tombstone_store.py:67` | `TombstoneEntry` (`models/tombstone.py:71`) | causal deletion markers (vclock merge); SQLite-backed; re-exported from `models/tombstone.py` |
| `SyncStateStore` / `FileVersion` | `models/version_store.py:106` / `models/version.py:70` | `FileVersion` TypedDict | 3-way merge state; SQLite-backed; `SyncStateStore` re-exported from `models/version.py` |
| `StateDb` | `models/sqlstore.py` | — | installation `syncstate.db` (ADR-0025) |
| folder marker | `models/folder.py` | — | `.hsyncfolder` UUIDv4 + `default_state_dir` |

## File

- Attributes: `filepath, name, ctime, mtime, size, sha256sum, permissions`
  (constructor `models/file.py`). `permissions` is an **octal string**
  (e.g. `"644"`), produced via `permissions.get_permissions` (see utilities).
- SHA-256 cache keyed by `(file_path, mtime, size)`: `_get_cached_sha256`
  (`models/file.py`), `_set_cached_sha256`, invalidation
  `invalidate_sha256_cache`, full clear `clear_sha256_cache`. The **size is
  part of the validity key**: on filesystems with coarse 1 s mtime
  granularity a same-second same-size rewrite is indistinguishable, but a
  size change always drops the stale digest.
- `File.get` / `Dir.get` are **race-safe**: any `OSError` from
  stat/hash/permission reads (file vanished mid-scan) degrades to `None`
  instead of aborting the sync cycle.
- Partial-download exclusion: `is_partial_file` (`models/file.py:92`) matches the
  `PARTIAL_DOWNLOAD_SUFFIX = ".part"` constant (`constants.py:74`); applied in
  the ignore matcher (`hsync_common.ignore.IgnoreMatcher`).
- Hidden detection: `is_hidden_file` (`models/file.py:154`).

## Event / SyncAction

- `EventName` (`models/event.py:44`): `added, modified, renamed, deleted, symlink`.
- `is_valid_cid` (`models/event.py:29`): strictly-alphanumeric client-ID check
  (`^[A-Za-z0-9]{21}$`) for peer-supplied client IDs — no `-`/`_`, so a cid
  always starts with a letter/digit (`fullmatch` — a trailing `\n` is rejected).
- `Event.__init__` normalizes src/dst paths **in place** (the caller's objects
  are rewritten). Stripping `localpath` is component-aware via
  `Path.relative_to`: a path merely sharing the string prefix (e.g. `/base2`
  vs `/base`) is kept verbatim instead of being mangled (`2/x`).
- `SyncActionName` (`models/sync_action.py:14`): `download, upload, delete,
  delete_remote, upload_symlink, download_symlink, nothing`. The two
  symlink actions replicate the LINK STRUCTURALLY (pair path+target) during
  the full-sync reconcile — never file content; they are transport-agnostic
  (server `/symlinks` and LAN master share the same surface).
- `SyncAction.to_dict` (`models/sync_action.py:72`) serializes
  `file, name, timedelta, conflict` — the `conflict` flag is part of the
  serialized shape so the "preserve the local copy first" signal survives
  serialization.

## TombstoneStore (causal deletion markers)

- Key derivation hashed for privacy: `tombstone_key`/`relpath_in_bucket`
  live in `models/_util.py` and are re-exported from `models/tombstone.py`.
  `relpath_in_bucket` returns **`None`** for a path outside the bucket
  (component-aware `relative_to`; a sibling-prefix path like `/base2/x` vs
  `/base` is never mangled), never the bucket-root identity `""`: mapping an
  outside path to `tombstone_key("")` would corrupt the root's causal state.
  Callers skip `None`/`""` relpaths (`if not relpath`).
- `TombstoneEntry`: `{sha256: str|None, version_id: str, origin_cid: str|None,
  ts: int, vclock: dict[str,int]}` (`models/tombstone.py:71`).
- **Causal record** (`record`/`record_by_key`): the marker inherits the stored
  version clock for the path (`prev_vclock`) and is ticked by the deleter cid
  (`tick_vclock`) — the deletion is an operation in the same causal history as
  edits (ADR-0003). Without an origin cid the inherited clock is recorded
  un-ticked.
- **Causal merge** (`merge`, pure decision in `tombstone_merge_decision`,
  `models/tombstone.py:183`): dominance decides `adopt`/`keep`
  (`compare_vclocks`); true concurrency resolves via deterministic content
  tie-break (content hash → version_id → origin_cid); **`ts` never decides**.
- TTL GC via `prune()` bounded by `TOMBSTONE_TTL_DAYS_DEFAULT = 90`
  (`models/tombstone.py:59`) — a **storage bound only**, correctness does not
  depend on it.
- Strict wire validation (`merge()`/`load()` via `_sanitize_entry`,
  `models/tombstone.py:123`): keys and `sha256` must be sha256 hex (64),
  `ts` must be `0 < ts ≤ now + TOMBSTONE_MAX_CLOCK_SKEW_SECONDS` (300 s),
  the `vclock` must parse strictly (`_parse_vclock`, `:101`: dict, ≤
  `VCLOCK_MAX_ENTRIES` entries, non-negative int counters with `bool`
  rejected, valid cids only) — an entry without a valid clock is dropped,
  never loaded with a fabricated empty clock. Store capped at
  `TOMBSTONE_MAX_ENTRIES` (100 000) — anti-poisoning for LAN gossip payloads.
  Raw `ts` is also type-hardened: `bool` rejected outright, `int()` guarded
  against `OverflowError` from non-finite floats (JSON `Infinity`/`NaN` are
  accepted by `json.loads`).
- Cross-language parity: `protocol/fixtures.py` builds
  `causal-tombstone-scenarios` from `tombstone_merge_decision` (never
  hand-written); the committed JSON is replayed by the Android parity test.
- Persisted in the installation `syncstate.db` (`models/sqlstore.py`), keyed
  by folder UUID from `.hsyncfolder` (`models/folder.py`, ADR-0025). The wire
  payload (`to_payload`) is unchanged. The store class lives in
  `models/tombstone_store.py:67` (re-exported from `models/tombstone.py`).

## Version / causal merge

- `FileVersion` TypedDict (`models/version.py:70`) carries per-file `base_hash`,
  `version_id`, `origin_cid`, `ts` (informational), `corrected_mtime`
  (ADR-0023) and the causal `vclock` (`dict[str, int]` mapping node cid →
  logical counter).
- `VersionInfo` TypedDict is the wire form (carried in `FileDict["version"]`):
  `vclock`, `version_id`, `origin_cid`, `ts`, `corrected_mtime` — no
  `base_hash` (the content hash is the enclosing `sha256sum`).
  `parse_version_info` tolerantly drops malformed payloads; an absent/malformed
  `corrected_mtime` parses as 0 (unknown ⇒ hash fallback).
- Vector-clock ops: `compare_vclocks` (`VClockOrder`), `tick_vclock`,
  `merge_vclocks`.
- Core resolver: `resolve_three_way(local_hash, local_vclock, remote_hash,
  remote_vclock, base_hash, *, local_corrected_mtime=0,
  remote_corrected_mtime=0)` — content identity first, then causal dominance,
  then the **corrected-mtime tie-break** (higher corrected_mtime wins the path;
  a missing side or a tie falls back to highest SHA-256); never raw wall clock
  ([ADR-0022](../docs/internal/adr/0022-causal-vector-clock-conflict-model.md),
  [ADR-0023](../docs/internal/adr/0023-corrected-mtime-tie-break.md)).
- `SyncDecision`: `in_sync`, `upload`, `download`, `conflict_upload`,
  `conflict_download` (tie-break loser preserved as a conflicted copy).
- Version-id minting: `new_version_id` (`_VERSION_ID_BYTES = 16`).
- `SyncStateStore` persists per-file versions for the next reconciliation in
  the installation `syncstate.db` (`models/sqlstore.py`), keyed by folder UUID
  (`models/folder.py`, ADR-0025). Constructor is `db_path=` + `folder_id=`;
  method semantics (`record`/`clear`/`retain`/`get`/`load`/`save`) are
  unchanged. The model is strictly causal: `load()` drops rows without a
  structurally valid `vclock` (no fabricated empty clocks) — a corrupted row
  degrades entry-by-entry instead of crashing startup. `corrected_mtime` is
  persisted alongside and defaulted to 0 when NULL. The store class lives in
  `models/version_store.py:106` (re-exported from `models/version.py`).

## Delta Transfer Models (`models/delta.py`)

Wire models for rsync-style delta transfer (block-level sync):

- `BlockSignature` / `BlockSignatureDict` (`models/delta.py:87`): signature of a
  single base-file block (index, offset, length, weak Adler32, strong SHA-256)
- `DeltaOp` / `DeltaOpDict` (`models/delta.py:108`): reconstruction operation
  (copy from base or data from literal payload)
- `DeltaInstructions` / `DeltaInstructionsDict` (`models/delta.py:137`): ordered
  operations to rebuild the new file from base + literals
- `DeltaApplyMetadata` / `DeltaApplyMetadataDict` (`models/delta.py:160`):
  metadata for POST /delta/apply (upload delta) — includes cid, base/new SHA-256,
  new_size, block_size, compressed flag, ops, optional mtime/permissions

Sanitizers: `sanitize_block_signature` (`:165`), `sanitize_delta_op` (`:193`),
`sanitize_signature_list` (`:219`), `sanitize_op_list` (`:232`) — validate
untrusted payloads from peers, rejecting malformed shapes to prevent crashes
or poisoning.

## Serialization & protocol tie-in

`File`/`Dir`/`Symlink`/`Event` shapes are reflected into the WS and LAN JSON
Schemas by the builders in `protocol/schemas.py` (`_file_object` `:82`,
`_dir_object` `:103`, `_symlink_object` `:117`, `_event_message` `:135`), so a
model field change must regenerate the contract artifacts (see
[modules/protocol.md](modules/protocol.md)).

> Human-readable attribute tables and narrative: `../docs/architecture.md` (Models).
