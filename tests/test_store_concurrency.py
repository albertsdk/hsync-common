"""Concurrency stress for the SQLite-backed causal stores (ADR-0025).

A process owns one installation-level ``syncstate.db`` shared by every folder,
so the store layer must tolerate several writers persisting into the same file
at once (``hsync-server`` keeps one version/tombstone store per bucket;
``hsync-client`` flushes its stores from the transfer paths).

The documented contract pinned here: each writer owns a *distinct* store
instance -- mutations of one instance are serialized by its caller (see
``hsync_server.store_registry.PerBucketStores``) -- while every instance
persists into the same database file, whose WAL bootstrap and schema creation
may happen concurrently on the very first writers. ``save()`` is incremental
and transactional, so interleaved flushes must neither lose dirty keys nor
raise ``database is locked`` / ``table is locked``.

Each test re-opens the database afterwards and asserts the persisted rows, then
runs ``PRAGMA integrity_check`` so a torn write cannot stay silent.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from hsync_common.models.sqlstore import get_state_db
from hsync_common.models.tombstone import TOMBSTONE_TTL_DAYS_DEFAULT
from hsync_common.models.tombstone_store import TombstoneStore
from hsync_common.models.version_store import SyncStateStore

_THREADS = 16
_ENTRIES = 20

# Well-formed 21-char cid (is_valid_cid-compliant) used as tombstone origin.
_CID = "TestClientA1234567890"


def _hash(folder: int, item: int, round_no: int = 0) -> str:
    """Deterministic 64-hex content hash for a (folder, item, round) triple."""
    return hashlib.sha256(f"{folder}:{item}:{round_no}".encode()).hexdigest()


def _paths(prefix: str, count: int = _ENTRIES) -> list[str]:
    """Bucket-relative paths used by every writer of a test."""
    return [f"{prefix}/file_{item:03d}.bin" for item in range(count)]


def _folders(count: int = _THREADS) -> dict[int, str]:
    """One distinct store folder UUID per writer."""
    return {i: str(uuid.uuid4()) for i in range(count)}


def _run_all(fn, count: int = _THREADS) -> list:
    """Run ``fn(i)`` on *count* threads; re-raise any worker exception."""
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(fn, i) for i in range(count)]
        return [f.result() for f in futures]


def _integrity_check(db_path: Path) -> None:
    """Assert the database is structurally sound and still in WAL mode."""
    db = get_state_db(db_path)
    assert db.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"


class TestConcurrentFirstWriters:
    def test_parallel_writers_bootstrap_and_persist(self, tmp_path: Path):
        db_path = tmp_path / "syncstate.db"
        folders = _folders()
        relpaths = _paths("shared")

        def writer(i: int) -> None:
            versions = SyncStateStore(db_path=db_path, folder_id=folders[i])
            tombstones = TombstoneStore(db_path=db_path, folder_id=folders[i])
            for item, rel in enumerate(relpaths):
                versions.record(rel, base_hash=_hash(i, item))
            for rel in relpaths[::2]:
                tombstones.record(rel, sha256sum=_hash(i, 0), origin_cid=_CID)
            versions.save()
            tombstones.save()

        _run_all(writer)

        db = get_state_db(db_path)
        for i, folder_id in folders.items():
            assert db.count_versions(folder_id) == _ENTRIES
            reloaded = SyncStateStore(db_path=db_path, folder_id=folder_id)
            reloaded.load()
            assert len(reloaded) == _ENTRIES
            for item, rel in enumerate(relpaths):
                assert reloaded.base_hash(rel) == _hash(i, item)
            tombstones = TombstoneStore(db_path=db_path, folder_id=folder_id)
            tombstones.load()
            assert len(tombstones) == _ENTRIES // 2
            assert tombstones.get(relpaths[0]) is not None
        _integrity_check(db_path)


class TestInterleavedWriters:
    def test_interleaved_save_cycles_keep_final_rows(self, tmp_path: Path):
        db_path = tmp_path / "syncstate.db"
        folders = _folders()
        relpaths = _paths("cycle")
        rounds = 3
        dropped = relpaths[::4]
        dropped_set = set(dropped)
        kept = [rel for rel in relpaths if rel not in dropped_set]

        def writer(i: int) -> None:
            store = SyncStateStore(db_path=db_path, folder_id=folders[i])
            for round_no in range(rounds):
                for item, rel in enumerate(relpaths):
                    store.record(rel, base_hash=_hash(i, item, round_no))
                for rel in dropped:
                    store.clear(rel)
                store.save()
                # A concurrent reader must always load a consistent snapshot.
                reader = SyncStateStore(db_path=db_path, folder_id=folders[i])
                reader.load()

        _run_all(writer)

        for i, folder_id in folders.items():
            reloaded = SyncStateStore(db_path=db_path, folder_id=folder_id)
            reloaded.load()
            assert len(reloaded) == len(kept)
            for rel in kept:
                assert reloaded.base_hash(rel) == _hash(i, relpaths.index(rel), rounds - 1)
            for rel in dropped:
                assert reloaded.base_hash(rel) is None
        db = get_state_db(db_path)
        for folder_id in folders.values():
            assert db.count_versions(folder_id) == len(kept)
        _integrity_check(db_path)


class TestConcurrentTombstoneLifecycle:
    def test_parallel_merge_then_prune(self, tmp_path: Path):
        db_path = tmp_path / "syncstate.db"
        relpaths = _paths("gone")

        source = TombstoneStore(db_path=db_path, folder_id=str(uuid.uuid4()))
        for item, rel in enumerate(relpaths):
            source.record(rel, sha256sum=_hash(0, item), origin_cid=_CID)
        payload = source.to_payload()
        assert len(payload) == _ENTRIES

        folders = _folders()

        def merger(i: int) -> int:
            store = TombstoneStore(db_path=db_path, folder_id=folders[i])
            merged = store.merge(payload)
            store.save()
            return merged

        assert _run_all(merger) == [_ENTRIES] * _THREADS

        db = get_state_db(db_path)
        for folder_id in folders.values():
            reloaded = TombstoneStore(db_path=db_path, folder_id=folder_id)
            reloaded.load()
            assert len(reloaded) == _ENTRIES

        # Prune past the retention window: every merged marker expires and the
        # concurrent row deletes must all land in the database.
        future = int(time.time()) + (TOMBSTONE_TTL_DAYS_DEFAULT + 1) * 86400

        def pruner(i: int) -> int:
            store = TombstoneStore(db_path=db_path, folder_id=folders[i])
            store.load()
            removed = store.prune(now=future)
            store.save()
            return removed

        assert _run_all(pruner) == [_ENTRIES] * _THREADS
        for folder_id in folders.values():
            assert db.iter_tombstones(folder_id) == []
        _integrity_check(db_path)
