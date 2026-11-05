"""In-memory token-bucket rate limiters — RAM only, no persistence.

A token bucket expresses an ``N/min (burst B)`` policy exactly: the bucket holds
at most ``capacity`` tokens (the burst) and is refilled at ``refill`` tokens per
``window`` seconds (the sustained rate), lazily on each check using a monotonic
clock. Expired state is pruned lazily too; nothing is ever written to disk.

Declared consumers: ``hsync-client`` (P2P listener new-connection limiting) and
``hsync-rendezvous/python`` (admission/query/register limits).
"""

from __future__ import annotations

import time

__all__ = [
    "RateLimitKey",
    "TokenBucket",
    "TokenBucketLimiter",
]

RateLimitKey = str


class TokenBucket:
    """Single-bucket token limiter for one fixed policy (no per-key map).

    ``charge(size)`` consumes *size* tokens and returns ``None`` when they fit,
    or the seconds to wait until they do; tokens are **not** consumed on the
    failure path. ``acquire()`` is the one-token sugar for the common
    per-message case. State refills lazily on a monotonic clock and ``now`` is
    injectable for deterministic tests.

    This is the standalone sibling of :class:`TokenBucketLimiter`: use it when a
    component has exactly one bucket (a WebSocket message budget, a relay
    byte-rate shaper) instead of one bucket per IP/key. A zero capacity or refill
    is allowed and yields a bucket that never admits work.
    """

    def __init__(self, capacity: float, refill: float, window: float = 1.0) -> None:
        if capacity < 0 or refill < 0 or window <= 0:
            raise ValueError("capacity/refill must be non-negative and window positive")
        self._capacity = float(capacity)
        self._rate = refill / window
        self._tokens = float(capacity)
        self._stamp = time.monotonic()

    def _refill(self, now: float) -> None:
        elapsed = now - self._stamp
        if elapsed < 0.0:
            elapsed = 0.0
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._stamp = now

    def charge(self, size: float, now: float | None = None) -> float | None:
        """Consume *size* tokens; ``None`` when they fit, else seconds to wait."""
        if size < 0:
            raise ValueError("size must be non-negative")
        now = now if now is not None else time.monotonic()
        self._refill(now)
        if self._tokens >= size:
            self._tokens -= size
            return None
        if self._rate <= 0:
            return float("inf")
        return (size - self._tokens) / self._rate

    def acquire(self, now: float | None = None) -> bool:
        """Consume one token, returning True, or False when the bucket is empty."""
        return self.charge(1.0, now) is None


class TokenBucketLimiter:
    """Per-key token bucket: at most ``capacity`` tokens, refill ``refill``/window.

    ``allow(key)`` consumes one token and returns True, or returns False when
    the bucket is empty; ``retry_after(key)`` then reports the seconds until
    the next token is available so the caller can answer with an explicit
    ``retry_after`` instead of silently dropping. Bucket state initialises on
    first use and refills lazily on each check (monotonic clock); a caller may
    pass ``now`` explicitly for deterministic tests.

    ``max_keys`` bounds the tracked-key population: under IP/bucket churn an
    adversarial caller could otherwise grow the map without limit, so a new key
    evicts the least-recently-used one once the ceiling is reached. Evicting the
    LRU key is decision-neutral for an inactive bucket (it had the longest time
    to refill) and, crucially, never resets a bucket that is still being used —
    ``has_tokens``/``retry_after`` peeks do not refresh the recency, only a real
    ``allow`` does.
    """

    def __init__(
        self,
        capacity: int,
        refill: float,
        window: float = 60.0,
        *,
        max_keys: int | None = None,
    ) -> None:
        if capacity < 1 or refill <= 0 or window <= 0:
            raise ValueError("capacity/refill/window must be positive")
        if max_keys is not None and max_keys < 1:
            raise ValueError("max_keys must be positive when set")
        self._capacity = float(capacity)
        self._rate = refill / window  # tokens per second
        self._max_keys = max_keys
        # One entry per tracked key: ``key -> (tokens, updated_at)``, ordered
        # least-recently-used first so its dict order drives eviction. A second
        # OrderedDict (as before) only duplicated the key and the per-entry
        # overhead: the limiter state runs into the millions of keys under churn.
        self._buckets: dict[RateLimitKey, tuple[float, float]] = {}

    def allow(self, key: RateLimitKey, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        # Inlined _refill(): the check is the per-frame hot path (one call per
        # admitted metric), so it avoids a second method call.
        entry = self._buckets.get(key)
        if entry is None:
            self._make_room()
            tokens = self._capacity
        else:
            elapsed = now - entry[1]
            if elapsed < 0.0:
                elapsed = 0.0
            tokens = entry[0] + elapsed * self._rate
            if tokens > self._capacity:
                tokens = self._capacity
            # Re-insert so this key becomes the most-recently-used (a plain dict
            # assignment on an existing key would keep its old position).
            del self._buckets[key]
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1.0, now)
        return True

    def has_tokens(self, key: RateLimitKey, now: float | None = None) -> bool:
        """True when ``key`` has at least one token, without consuming it.

        Used by the pre-parse gate: an IP whose malformed-frame bucket has run
        dry is dropped before the parser runs, so the parse-storm budget truly
        bounds CPU instead of only labelling the drop.
        """
        entry = self._buckets.get(key)
        if entry is None:
            return self._capacity >= 1.0
        now = now if now is not None else time.monotonic()
        elapsed = max(0.0, now - entry[1])
        tokens = min(self._capacity, entry[0] + elapsed * self._rate)
        return tokens >= 1.0

    def refund(self, key: RateLimitKey) -> None:
        """Return one consumed token to ``key`` (never above ``capacity``).

        The inverse of a consumed :meth:`allow`, for a caller that admitted work
        and then found it should not have been charged against this budget. Used
        by the rendezvous node's TLS/TCP relay fan-out exemption: an admitted
        connection that turns out to be a relay ``relay_attach`` returns the
        handshake token its admission consumed, so a listener's fan-out is
        bounded by the relay session quotas instead of the generic per-IP
        handshake budget. An unknown key is a no-op, and the count never exceeds
        ``capacity`` (the value a first-use bucket starts from), so a refund can
        never grant more budget than a fresh bucket would.
        """
        entry = self._buckets.get(key)
        if entry is None:
            return
        tokens, ts = entry
        self._buckets[key] = (min(self._capacity, tokens + 1.0), ts)

    def _make_room(self) -> None:
        """Evict the least-recently-used key when the population ceiling is reached."""
        if self._max_keys is None or len(self._buckets) < self._max_keys:
            return
        del self._buckets[next(iter(self._buckets))]

    def retry_after(self, key: RateLimitKey, now: float | None = None) -> int:
        """Seconds until the next token of ``key`` becomes available (>=1)."""
        now = now if now is not None else time.monotonic()
        tokens = self._refill(key, now)
        if tokens >= 1.0:
            return 1
        seconds = (1.0 - tokens) / self._rate
        return max(1, int(seconds) + 1)

    def evict_stale(self, now: float | None = None) -> int:
        """Drop buckets that have fully refilled since their last check.

        A key untouched for ``capacity / rate`` seconds refills to exactly
        ``capacity`` — the value a first-use key starts from — so evicting it is
        behaviour-identical to keeping it, and bounds memory under IP churn.
        """
        now = now if now is not None else time.monotonic()
        horizon = self._capacity / self._rate
        stale = [k for k, (_, ts) in self._buckets.items() if now - ts >= horizon]
        for k in stale:
            del self._buckets[k]
        return len(stale)

    def _refill(self, key: RateLimitKey, now: float) -> float:
        """Return the (unconsumed) token count after applying the elapsed refill."""
        entry = self._buckets.get(key)
        if entry is None:
            self._make_room()
            self._buckets[key] = (self._capacity, now)
            return self._capacity
        elapsed = max(0.0, now - entry[1])
        tokens = min(self._capacity, entry[0] + elapsed * self._rate)
        self._buckets[key] = (tokens, now)
        return tokens
