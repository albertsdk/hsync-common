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
| `TombstoneStore` | `models/tombstone.py:101` | `TombstoneEntry` (`models/tombstone.py:42`) | deletion markers, LWW merge |
| `SyncStateStore` / `FileVersion` | `models/version.py:100` / `:46` | `FileVersion` TypedDict | 3-way merge state |

## File

- Attributes: `filepath, name, ctime, mtime, size, sha256sum, permissions`
  (constructor `models/file.py:178`). `permissions` is an **octal string**
  (e.g. `"644"`), produced via `permissions.get_permissions` (see utilities).
- SHA-256 cache keyed by `(file_path, mtime)`: `_get_cached_sha256`
  (`models/file.py:56`), `_set_cached_sha256` (`:67`), invalidation
  `invalidate_sha256_cache` (`:43`), full clear `clear_sha256_cache` (`:34`).
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
  delete_remote, nothing`.
- `SyncAction.to_dict` (`models/sync_action.py:72`) serializes
  `file, name, timedelta, conflict` — the `conflict` flag is part of the
  serialized shape so the "preserve the local copy first" signal survives
  serialization.

## TombstoneStore (deletion markers)

- Key derivation hashed for privacy: `tombstone_key` (`models/tombstone.py:91`),
  bucket-relative path via `relpath_in_bucket` (`:96`).
- `TombstoneEntry`: `{ts: int, sha256: str|None}` (`models/tombstone.py:42`).
- LWW semantics in `record()` / `merge()` keep newest `ts`; TTL GC via `prune()`
  bounded by `TOMBSTONE_TTL_DAYS_DEFAULT = 30` (`models/tombstone.py:29`).
- Untrusted-input hardening (`merge()`/`load()` via `_sanitize_entry`,
  `models/tombstone.py:59`): keys and `sha256` must be sha256 hex (64),
  `ts` must be `0 < ts ≤ now + TOMBSTONE_MAX_CLOCK_SKEW_SECONDS` (300 s, `:35`),
  store capped at `TOMBSTONE_MAX_ENTRIES` (100 000, `:39`) — anti-poisoning
  for LAN gossip payloads. Raw `ts` is also type-hardened: `bool` rejected
  outright, `int()` guarded against `OverflowError` from non-finite floats
  (JSON `Infinity`/`NaN` are accepted by `json.loads`).
- Persisted to the `.hsynctombstones` side-car (`constants.py:43`).

## Version / three-way merge

- `FileVersion` TypedDict (`models/version.py:46`) + `SyncDecision` enum
  (`models/version.py:55`).
- Core resolver: `resolve_three_way` (`models/version.py:70`) — compares
  base/local/remote hashes to pick keep/overwrite/conflict.
- Version-id minting: `new_version_id` (`models/version.py:65`,
  `_VERSION_ID_BYTES = 16`).
- `SyncStateStore` (`models/version.py:100`) persists per-file base versions for
  the next reconciliation; backs the `.hsyncstate` side-car (`constants.py:51`).
  `load()` is hardened like `TombstoneStore.load()`: a non-dict `versions`
  member, non-dict entries, and `ts` values that are bool/non-numeric/non-finite
  are skipped instead of crashing startup.

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
