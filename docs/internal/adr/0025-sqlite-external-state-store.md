# ADR 0025 — SQLite external state store

- **Status:** Accepted
- **Date:** 2026-08-18

## Context

Persisting causal version metadata (ADR-0022) and deletion markers (ADR-0003) as
per-peer JSON side-cars inside each synced bucket (``.hsyncstate``,
``.hsynctombstones``) has no WAL, no checksums, and no lock of its own: every
save rewrites the full map (``json.dumps`` + atomic ``tmp``/``replace``) and
every start loads the full file into memory, so at scale it is O(N) per flush,
crash-unsafe beyond the rename, and grows with peer count because each
``vclock`` can hold up to 256 entries.

The wire protocol is not the problem. Upload, listing, tombstone gossip,
WS/p2p events and the ``vector_clocks`` capability already carry JSON
``vclock`` / ``version`` dicts (``api/1``, ``ws/1``, ``p2p/1``). Only local
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

There are no production deployments, so the store is specified as if the
projects were born with it: no JSON→SQLite migration, no ``.bak`` files, no
legacy branches. A folder without a marker is a new folder (full rescan;
content converges by hash; conflict copies are preserved).

## Decision

We will persist causal versions and tombstones in **per-folder SQLite
databases stored outside the synced bucket**, keyed by a **folder UUID**
recorded in a small marker file inside the bucket. The client keeps one DB per
folder under its device directory plus a small per-device index; the server
keeps one DB per bucket plus a global auth DB. A process-wide
``HSYNC_STATE_DB`` override collapses this to a single DB for that process
(used by tests and manual isolation).

### Storage locations

| Platform | DB location | Marker in bucket |
|---|---|---|
| Client / p2p master (Python) | ``<device_dir>/syncstate/<folder_uuid>.db`` (``<device_dir>`` = ``$HSYNC_DEVICE_DIR`` or ``$XDG_STATE_HOME/hsync/device``); ``<device_dir>/syncstate/index.db`` maps ``canonical_path`` → UUID for re-anchoring | ``.hsyncfolder`` (UUIDv4 text + newline) |
| Server (Python) | ``{state_dir}/server/<bucket>.db`` (``get_state_dir()``; env ``HSYNC_STATE_DIR``); ``{state_dir}/server/auth.db`` (global auth) | none; the file is named by the (validated) bucket name |
| Android | ``<filesDir>/syncstate/<uuid>.db`` | same ``.hsyncfolder`` marker (SAF/path) |

``HSYNC_STATE_DB``, when set, is the whole DB path for that process (client or
server): the per-folder / per-bucket / index files are not opened. This keeps a
single-file mode available for tests and manual isolation without re-deriving
the layout.

### Schema

Each per-folder / per-bucket DB uses the same tables as before — ``folders``
(the client index DB holds only this mapping), ``buckets`` (server-only), and
``versions`` / ``tombstones`` keyed by ``folder_id``. ``vclock`` remains a JSON
string validated by the existing parsers (``parse_version_info`` /
``parse_vclock`` in Python; ``parseStoredVclock`` on Android).
``ts`` and ``corrected_mtime`` are ``REAL`` so int|float JSON parity is
preserved. Version and tombstone keys stay the existing
``tombstone_key(relpath)`` hashes (privacy-preserving, shared with
Android).

### Folder ID lifecycle

1. First run: no marker → generate UUIDv4, write atomically (tmp+rename),
   create ``<device_dir>/syncstate/<uuid>.db`` and record the
   ``canonical_path`` in the per-device index.
2. Normal run: read marker → open ``<device_dir>/syncstate/<uuid>.db`` (state
   re-anchors across rename/move because the marker travels with the folder).
3. Copied directory (duplicated marker, both paths still exist): treat the
   copy as a new folder (new UUID, new DB, full rescan). Content identity is
   preserved by hashes and ``_conflicted_copy_``.
4. Marker missing, index has the path: adopt the recorded UUID (re-anchor). If
   the path is unknown, treat as new. A corrupt index fails closed (a new UUID
   is minted); do not guess by similarity.
5. Server: one DB per bucket named by the bucket; the UUID is minted at first
   bucket access and stored in that file's ``buckets`` table; never written
   into served bucket dirs.

### Transactions and PRAGMA

- ``sqlite3`` with ``isolation_level=None`` (autocommit); one statement per
  logical mutation. A sync-cycle ``flush()`` wraps pending writes in
  ``BEGIN IMMEDIATE … COMMIT``. Realtime single-row flushes (p2p delete)
  are one statement + commit.
- ``journal_mode=WAL``, ``synchronous=FULL``, ``busy_timeout=5000``,
  ``foreign_keys=ON``, ``auto_vacuum=INCREMENTAL``, ``user_version=1``. WAL
  probe falls back to ``journal_mode=DELETE`` on filesystems that reject WAL.
- ``retain()`` uses a temp-table anti-join so SQLite's parameter limit is
  never hit.

### Maintenance

Row pruning (``retain`` and tombstone TTL) deletes rows but the freed pages
would linger in the file without auto-vacuum. ``auto_vacuum=INCREMENTAL`` is
set before the schema is created, and the freed space is reclaimed by:

- **Incremental vacuum** — ``StateDb.incremental_vacuum(pages)`` (and the
  best-effort ``incremental_vacuum_state_db`` / ``vacuum_state_db`` /
  ``state_db_freelist_count`` module helpers in ``models/sqlstore.py``) removes
  up to *pages* free pages per call in place (no-op for ``pages <= 0``). The
  client invokes it throttled at the end of every sync cycle; the server runs
  it from a periodic background task
  (``hsync-server/hsync_server/state_maintenance.py``).
- **Full VACUUM at process boundaries** — ``StateDb.vacuum()`` rebuilds the
  file (autocommit, no in-flight statements). The server runs it at startup
  and graceful shutdown; the client at shutdown
  (``hsync-client/hsync_client/state_maintenance.py``). The server's startup
  VACUUM is **gated on the freelist size** (``state_db_freelist_count``) so a
  clean restart — whose shutdown VACUUM already reclaimed to zero — skips the
  redundant rebuild, and the boundary VACUUM is **single-flight across
  uvicorn workers** via a non-blocking ``flock`` on a sidecar lock file.

The cadence is a single policy in ``models/sqlstore.py``
(``INCREMENTAL_VACUUM_INTERVAL_S`` / ``INCREMENTAL_VACUUM_PAGES``); pruning
correctness never depends on it (space reclamation is purely a storage bound).

### Wire hardening

``.hsyncfolder`` is in ``INTERNAL_FILENAMES`` and must never be
accepted from the wire. ``.hsyncstate`` / ``.hsynctombstones`` are rejected so
they can never be written through the sync channel. The wire format itself is
untouched.

### Governed code

- ``hsync_common/constants.py`` — ``HSYNCFOLDER_FILENAME``,
  ``HSYNC_STATE_DIR_ENV``, ``SYNCSTATE_DB_FILENAME``
- ``hsync_common/models/folder.py`` — marker + state-dir helpers
- ``hsync_common/models/sqlstore.py`` — connection, schema, statements
- ``hsync_common/models/version_store.py`` — ``SyncStateStore`` SQLite backend (re-exported from ``models/version.py``)
- ``hsync_common/models/tombstone_store.py`` — ``TombstoneStore`` SQLite backend (re-exported from ``models/tombstone.py``)
- ``hsync_common/path_validation.py`` — ``INTERNAL_FILENAMES``
- Consumers: ``hsync-client`` ``sync_state.py`` / ``tombstones.py``,
  ``hsync-server`` ``versions.py`` / ``tombstones.py`` / ``config.py``,
  ``hsync-android`` ``SyncStateManager`` / ``Tombstones.kt``

## Consequences

- Crash-safety is SQLite ACID on the system filesystem; copying a bucket
  copies only user data and the marker.
- An unmarked folder is treated as new (full rescan). There is no JSON side-car
  import.
- Public store method semantics (``record`` / ``clear`` / ``retain`` /
  ``get`` / ``load`` / ``save`` / tombstone merge) are unchanged; only
  construction (``db_path`` + ``folder_id``) and the backing file differ.
- Client, server and Android share the same store through their own wrappers;
  the shared wire fixtures, schemas and OpenAPI snapshots stay byte-identical.
- The SQLite + ``.hsyncfolder`` model is the only persistence model; the causal
  algorithms of ADR-0003 / ADR-0016 / ADR-0022 are unchanged.
