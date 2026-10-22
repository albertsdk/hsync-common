# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Unit tests for the shared delta download-token registry."""

from __future__ import annotations

import pytest

from hsync_common.delta import (
    DeltaTokenStore,
    TokenStoreFull,
    TokenStoreStorageFull,
)


def _store(tmp_path, **kwargs) -> DeltaTokenStore:
    """A store bound to an isolated payload directory."""
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    return DeltaTokenStore(
        ttl=kwargs.pop("ttl", 300),
        max_tokens=kwargs.pop("max_tokens", 10),
        tmp_dir=lambda: payload_dir,
        **kwargs,
    )


class TestIssueAndConsume:
    def test_issue_parks_the_payload_and_consumes_once(self, tmp_path):
        store = _store(tmp_path)
        token = store.issue(bucket="b1", payload=b"abc", compressed=False)

        entry = store.lookup(token)
        assert entry is not None
        assert entry.bucket == "b1"
        assert entry.compressed is False
        assert (tmp_path / "payloads").joinpath(f"delta_{token}.bin").read_bytes() == b"abc"

        assert store.consume(token) is entry
        assert store.lookup(token) is None
        assert store.consume(token) is None

    def test_meta_is_preserved(self, tmp_path):
        store = _store(tmp_path)
        token = store.issue(bucket="b1", payload=b"x", compressed=True, meta={"relpath": "a/b.txt"})
        entry = store.lookup(token)
        assert entry is not None
        assert entry.compressed is True
        assert entry.meta["relpath"] == "a/b.txt"

    def test_issue_from_file_moves_the_payload(self, tmp_path):
        store = _store(tmp_path)
        source = tmp_path / "literal.bin"
        source.write_bytes(b"payload")

        token = store.issue_from_file(
            bucket="b1", payload_file=str(source), size=7, compressed=False
        )

        assert not source.exists()
        entry = store.lookup(token)
        assert entry is not None
        assert (tmp_path / "payloads").joinpath(f"delta_{token}.bin").read_bytes() == b"payload"

    def test_issue_from_missing_file_propagates_oserror(self, tmp_path):
        store = _store(tmp_path)
        with pytest.raises(OSError):
            store.issue_from_file(
                bucket="b1",
                payload_file=str(tmp_path / "missing.bin"),
                size=1,
                compressed=False,
            )


class TestLimits:
    def test_token_cap_raises(self, tmp_path):
        store = _store(tmp_path, max_tokens=1)
        store.issue(bucket="b1", payload=b"a", compressed=False)
        with pytest.raises(TokenStoreFull):
            store.issue(bucket="b1", payload=b"b", compressed=False)

    def test_storage_cap_raises(self, tmp_path):
        store = _store(tmp_path, max_storage_bytes=4)
        store.issue(bucket="b1", payload=b"abcd", compressed=False)
        with pytest.raises(TokenStoreStorageFull):
            store.issue(bucket="b1", payload=b"e", compressed=False)

    def test_count_and_reset(self, tmp_path):
        store = _store(tmp_path)
        first = store.issue(bucket="b1", payload=b"a", compressed=False)
        second = store.issue(bucket="b1", payload=b"b", compressed=False)
        payload_dir = tmp_path / "payloads"
        assert store.count == 2
        files = sorted(p.name for p in payload_dir.iterdir())
        assert files == sorted([f"delta_{first}.bin", f"delta_{second}.bin"])

        store.reset()

        assert store.count == 0
        assert store.lookup(first) is None
        assert list(payload_dir.iterdir()) == []


class TestExpiry:
    def test_expired_entries_are_reaped(self, tmp_path):
        store = _store(tmp_path, ttl=10)
        token = store.issue(bucket="b1", payload=b"a", compressed=False)
        entry = store.lookup(token)
        assert entry is not None

        assert store.is_expired(entry, now=entry.created + 11) is True
        assert store.cleanup(now=entry.created + 11) == 1
        assert store.lookup(token) is None
        assert list((tmp_path / "payloads").iterdir()) == []

    def test_discard_drops_payload(self, tmp_path):
        store = _store(tmp_path)
        token = store.issue(bucket="b1", payload=b"a", compressed=False)
        store.discard(token)
        assert store.lookup(token) is None
        assert list((tmp_path / "payloads").iterdir()) == []
