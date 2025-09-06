# ADR 0025 — SQLite external state store

- **Status:** Accepted
- **Date:** 2026-08-18

## Context

Causal version metadata (ADR-0022) and deletion markers (ADR-0003) were
persisted as per-peer JSON side-cars inside each synced bucket
(``.hsyncstate``, ``.hsynctombstones``). Every save rewrote the full map
(``json.dumps`` + atomic ``tmp``/``replace``); every start loaded the full
file into memory. That design has no WAL, no checksums, and no lock of its
own. At scale it is O(N) per flush, crash-unsafe beyond the rename, and
grows with peer count because each ``vclock`` can hold up to 256 entries.

The wire protocol is not the problem. Upload, listing, tombstone gossip,
WS/LAN events and the ``vector_clocks`` capability already carry JSON
``vclock`` / ``version`` dicts (``api/1``, ``ws/1``, ``lan/1``). Only local
persistence is inadequate.

Alternatives considered:

| Option | Verdict |
|---|---|
| Keep JSON + gzip / dirty-flag | Treats symptoms; still O(N); no crash-safety |
| SQLite co-located in the bucket | ACID, but WAL/SHM artifacts inside user data, copy-consistency risk, exotic-FS failures |
| Native KV (LevelDB / RocksDB / LMDB) | Native deps and operational burden with no benefit for this workload |
| External SQLite + folder-ID marker (Syncthing model) | WAL+FULL on the system FS, zero engine artifacts in user data, same shape on Python and Android |

Industry reference: Syncthing keeps a single external index and only a small
``.stfolder`` marker inside the folder; Dropbox/Nextcloud journals live
outside user folders.

There are no production deployments. The store is specified as if the
projects were born with it: no JSON→SQLite migration, no ``.bak`` files, no
legacy branches. A folder without a marker is a new folder (full rescan;
content converges by hash; conflict copies are preserved).

## Decision

We will persist causal versions and tombstones in a **single
installation-level SQLite database stored outside the synced bucket**,
keyed by a **folder UUID** recorded in a small marker file inside the
bucket.

### Storage locations

| Platform | DB location | Marker in bucket |
|---|---|---|
| Client / LAN master (Python) | ``$XDG_STATE_HOME/hsync/syncstate.db`` (fallback ``~/.local/state/hsync/syncstate.db``; env ``HSYNC_STATE_DIR``) | ``.hsyncfolder`` (UUIDv4 text + newline) |
| Server (Python) | ``{state_dir}/syncstate.db`` (``get_state_dir()``; env ``HSYNC_STATE_DIR``) | none; ``buckets`` table maps bucket name → UUID |
| Android | ``<filesDir>/syncstate.db`` | same ``.hsyncfolder`` marker (SAF/path) |

### Schema

Tables ``folders``, ``buckets`` (server-only mapping), ``versions`` and
``tombstones``, all keyed by ``folder_id``. ``vclock`` remains a JSON
string validated by the existing parsers (``parse_version_info`` /
``parse_vclock`` in Python; ``parseStoredVclock`` on Android).
``ts`` and ``corrected_mtime`` are ``REAL`` so int|float JSON parity is
preserved. Version and tombstone keys stay the existing
``tombstone_key(relpath)`` hashes (privacy-preserving, shared with
Android).

### Folder ID lifecycle

1. First run: no marker → generate UUIDv4, write atomically (tmp+rename),
   insert ``folders`` row with ``canonical_path``.
2. Normal run: read marker → all state is keyed by that UUID (re-anchors
   across rename/move because the marker travels with the folder).
3. Copied directory (duplicated marker, both paths still exist): treat the
   copy as a new folder (new UUID, full rescan). Content identity is
   preserved by hashes and ``_conflicted_copy_``.
4. Marker missing, DB row exists: lookup by ``canonical_path``; if the
   path is gone, re-anchor or treat as new. Do not guess by similarity.
5. Server: UUID generated at first bucket access, stored in ``buckets``;
   never written into served bucket dirs.

### Transactions and PRAGMA

- ``sqlite3`` with ``isolation_level=None`` (autocommit); one statement per
  logical mutation. A sync-cycle ``flush()`` wraps pending writes in
  ``BEGIN IMMEDIATE … COMMIT``. Realtime single-row flushes (LAN delete)
  are one statement + commit.
- ``journal_mode=WAL``, ``synchronous=FULL``, ``busy_timeout=5000``,
  ``foreign_keys=ON``, ``user_version=1``. WAL probe falls back to
  ``journal_mode=DELETE`` on filesystems that reject WAL.
- ``retain()`` uses a temp-table anti-join so SQLite's parameter limit is
  never hit.

### Wire hardening

``.hsyncfolder`` is added to ``INTERNAL_FILENAMES`` and must never be
accepted from the wire. Legacy ``.hsyncstate`` / ``.hsynctombstones`` stay
rejected so an old peer cannot write them through the sync channel. The
wire format itself is untouched.

### Governed code (Phase 1 in ``hsync-common``; later phases in consumers)

- ``hsync_common/constants.py`` — ``HSYNCFOLDER_FILENAME``,
  ``HSYNC_STATE_DIR_ENV``, ``SYNCSTATE_DB_FILENAME``
- ``hsync_common/models/folder.py`` — marker + state-dir helpers
- ``hsync_common/models/sqlstore.py`` — connection, schema, statements
- ``hsync_common/models/version_store.py`` — ``SyncStateStore`` SQLite backend (re-exported from ``models/version.py``)
- ``hsync_common/models/tombstone_store.py`` — ``TombstoneStore`` SQLite backend (re-exported from ``models/tombstone.py``)
- ``hsync_common/path_validation.py`` — ``INTERNAL_FILENAMES``
- Consumers (later): ``hsync-client`` ``sync_state.py`` / ``tombstones.py``,
  ``hsync-server`` ``versions.py`` / ``tombstones.py`` / ``config.py``,
  ``hsync-android`` ``SyncStateManager`` / ``Tombstones.kt``

## Consequences

- Crash-safety is SQLite ACID on the system filesystem; copying a bucket
  copies only user data and the marker.
- First run after this change treats unmarked folders as new (full rescan).
  There is no JSON side-car import.
- Public store method semantics (``record`` / ``clear`` / ``retain`` /
  ``get`` / ``load`` / ``save`` / tombstone merge) stay the same; only
  construction (``db_path`` + ``folder_id``) and the backing file change.
- Client, server and Android must switch in lockstep with their own
  wrappers; the shared wire fixtures, schemas and OpenAPI snapshots must
  stay byte-identical.
- Documentation describes the SQLite + ``.hsyncfolder`` model as the only
  model. Persistence remarks in ADR-0003 / ADR-0016 / ADR-0022 are
  superseded by this record; the causal algorithms those ADRs define are
  unchanged.
