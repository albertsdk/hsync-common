# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Single-use download tokens for parked delta literal payloads.

A delta download parks the literal payload on disk and hands the peer a
short-lived, single-use token bound to the bucket it was issued for; the peer
fetches it later from the data endpoint. Keeping the payload on disk means a
multi-GB literal never has to sit in RAM, and the token registry stays tiny.

This module owns the whole lifecycle once, so the FastAPI server and the stdlib
P2P master cannot drift on TTL, capacity, storage accounting or single-use
semantics:

* tokens expire lazily (every access reaps the expired ones);
* the registry is capped both by count and by total parked bytes;
* the storage total is cached between mutations, so a steady-state issue costs
  one ``stat`` per token only after an invalidation (never per request);
* the payload file is adopted by an atomic ``os.replace`` into the token
  directory (same filesystem), never by copying it through RAM.

Consumers: ``hsync-server`` (``api/files/delta/tokens.py``),
``hsync-client`` (``p2p_delta.py``), tests.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "DeltaTokenEntry",
    "DeltaTokenStore",
    "TokenStoreFull",
    "TokenStoreStorageFull",
]


class TokenStoreFull(RuntimeError):
    """No new token can be issued: the live-token cap has been reached."""


class TokenStoreStorageFull(RuntimeError):
    """No new token can be issued: the parked-payload storage cap is reached."""


@dataclass(frozen=True)
class DeltaTokenEntry:
    """A parked literal payload awaiting download."""

    bucket: str
    payload_file: str  # absolute temp file holding the literal bytes
    compressed: bool  # payload is a single zstd frame
    created: float  # time.time() of issuance
    meta: Mapping[str, str] = field(default_factory=dict)
    # Issuer of the capability. Empty for producers that have no account
    # identity (e.g. the LAN P2P master); the REST server always sets it so a
    # leaked URL cannot be redeemed by a different account.
    account_id: str = ""


class DeltaTokenStore:
    """In-memory token registry with TTL, capacity caps and lazy expiry."""

    def __init__(
        self,
        *,
        ttl: int | Callable[[], int],
        max_tokens: int,
        tmp_dir: Callable[[], Path],
        max_storage_bytes: int | None = None,
        file_prefix: str = "delta_",
        on_change: Callable[[int, int], None] | None = None,
    ) -> None:
        """Create a registry.

        Args:
            ttl: Token lifetime in seconds, or a zero-argument callable for
                late binding to configuration.
            max_tokens: Hard cap on concurrently live tokens.
            tmp_dir: Zero-argument callable returning (and creating) the
                directory where payloads are parked.
            max_storage_bytes: Optional cap on the total parked payload size.
            file_prefix: Filename prefix for parked payloads.
            on_change: Optional observer called with ``(token_count,
                storage_bytes)`` after every mutation (metrics in the server).
        """
        self._ttl = ttl
        self._max_tokens = max_tokens
        self._tmp_dir = tmp_dir
        self._max_storage_bytes = max_storage_bytes
        self._file_prefix = file_prefix
        self._on_change = on_change
        # Cross-thread by design: issuance may run on worker threads while
        # lookups/consumption run on the event loop. The re-entrant lock lets
        # public methods compose (``issue`` → ``cleanup``) without deadlocking
        # and makes the token-count/storage checks atomic.
        self._lock = threading.RLock()
        self._tokens: dict[str, DeltaTokenEntry] = {}
        self._storage_size: int | None = None

    @property
    def ttl(self) -> int:
        """Token time-to-live in seconds (late binding when a callable was given)."""
        return self._ttl() if callable(self._ttl) else self._ttl

    @property
    def count(self) -> int:
        """Number of live tokens."""
        with self._lock:
            return len(self._tokens)

    def _notify_locked(self) -> None:
        """Report the current count/storage to the observer (lock held)."""
        if self._on_change is not None:
            self._on_change(len(self._tokens), self._get_total_storage_size())

    def _delete_payload(self, entry: DeltaTokenEntry) -> None:
        """Best-effort removal of the parked payload file."""
        with self._lock:
            try:
                Path(entry.payload_file).unlink(missing_ok=True)
            except OSError:
                pass
            self._storage_size = None
            self._notify_locked()

    def cleanup(self, now: float | None = None) -> int:
        """Drop expired tokens and their payload files; return the count."""
        cutoff = (now if now is not None else time.time()) - self.ttl
        with self._lock:
            expired = [t for t, e in self._tokens.items() if e.created < cutoff]
            for token in expired:
                entry = self._tokens.pop(token)
                try:
                    Path(entry.payload_file).unlink(missing_ok=True)
                except OSError:
                    pass
            if expired:
                self._storage_size = None
                self._notify_locked()
            return len(expired)

    def _get_total_storage_size(self) -> int:
        """Total size of all parked payload files (cached between mutations).

        The scan (one ``stat`` per live token) runs only after an invalidation,
        never on every issue, so the steady-state capacity check is O(1).
        """
        with self._lock:
            total = self._storage_size
            if total is None:
                total = 0
                for entry in self._tokens.values():
                    try:
                        total += Path(entry.payload_file).stat().st_size
                    except OSError:
                        pass
                self._storage_size = total
            return total

    def _reserve_locked(self, payload_size: int) -> int:
        """Enforce both caps; return the pre-issue storage total (lock held)."""
        self.cleanup()
        if len(self._tokens) >= self._max_tokens:
            raise TokenStoreFull("Too many active delta tokens")
        total_storage = self._get_total_storage_size()
        if (
            self._max_storage_bytes is not None
            and total_storage + payload_size > self._max_storage_bytes
        ):
            raise TokenStoreStorageFull("Delta temp storage limit exceeded")
        return total_storage

    def _register_locked(
        self,
        token: str,
        *,
        bucket: str,
        payload_file: str,
        compressed: bool,
        meta: Mapping[str, str] | None,
        total_storage: int,
        payload_size: int,
        account_id: str = "",
    ) -> None:
        """Register *token* and refresh the observer (called with the lock held)."""
        self._tokens[token] = DeltaTokenEntry(
            bucket=bucket,
            payload_file=payload_file,
            compressed=compressed,
            created=time.time(),
            meta=dict(meta or {}),
            account_id=account_id,
        )
        # The just-computed total plus the new payload is the new exact size, so
        # the cache stays valid without a rescan (O(1) update).
        self._storage_size = total_storage + payload_size
        self._notify_locked()

    def issue(
        self,
        *,
        bucket: str,
        payload: bytes,
        compressed: bool,
        meta: Mapping[str, str] | None = None,
        account_id: str = "",
    ) -> str:
        """Park *payload* on disk and return its download token (UUID v4)."""
        with self._lock:
            total_storage = self._reserve_locked(len(payload))
            token = uuid.uuid4().hex
            payload_file = str(self._tmp_dir() / f"{self._file_prefix}{token}.bin")
            with open(payload_file, "wb") as f:
                f.write(payload)
            self._register_locked(
                token,
                bucket=bucket,
                payload_file=payload_file,
                compressed=compressed,
                meta=meta,
                total_storage=total_storage,
                payload_size=len(payload),
                account_id=account_id,
            )
            return token

    def issue_from_file(
        self,
        *,
        bucket: str,
        payload_file: str,
        size: int,
        compressed: bool,
        meta: Mapping[str, str] | None = None,
        account_id: str = "",
    ) -> str:
        """Adopt an already-written payload file as a download token (UUID v4).

        The payload is *moved* into place (``os.replace``, atomic on the same
        filesystem) instead of being read into RAM. The caller owns
        *payload_file*: it must remove it when this raises.
        """
        with self._lock:
            total_storage = self._reserve_locked(size)
            token = uuid.uuid4().hex
            final_path = self._tmp_dir() / f"{self._file_prefix}{token}.bin"
            os.replace(payload_file, final_path)
            self._register_locked(
                token,
                bucket=bucket,
                payload_file=str(final_path),
                compressed=compressed,
                meta=meta,
                total_storage=total_storage,
                payload_size=size,
                account_id=account_id,
            )
            return token

    def lookup(self, token: str) -> DeltaTokenEntry | None:
        """Return the entry for *token*, or ``None`` when unknown."""
        with self._lock:
            return self._tokens.get(token)

    def is_expired(self, entry: DeltaTokenEntry, now: float | None = None) -> bool:
        """Return True when the entry is older than the configured TTL."""
        return entry.created < (now if now is not None else time.time()) - self.ttl

    def consume(self, token: str) -> DeltaTokenEntry | None:
        """Remove and return the entry for *token* (single-use semantics)."""
        with self._lock:
            entry = self._tokens.pop(token, None)
            if entry is not None:
                self._storage_size = None
                self._notify_locked()
            return entry

    def discard(self, token: str) -> None:
        """Drop a token and its payload file without serving it."""
        with self._lock:
            entry = self._tokens.pop(token, None)
            if entry is not None:
                self._storage_size = None
                self._delete_payload(entry)

    def reset(self) -> None:
        """Drop every token and parked payload (tests and lifecycle hooks)."""
        with self._lock:
            entries = list(self._tokens.values())
            self._tokens.clear()
            self._storage_size = 0
            for entry in entries:
                try:
                    Path(entry.payload_file).unlink(missing_ok=True)
                except OSError:
                    pass
            self._notify_locked()
