"""Tests for hsync_common.ratelimit (the shared token-bucket limiter)."""

from __future__ import annotations

import pytest

from hsync_common.ratelimit import TokenBucketLimiter


def test_allow_burst_then_refill_on_injected_clock() -> None:
    limiter = TokenBucketLimiter(capacity=2, refill=1.0, window=1.0)
    assert limiter.allow("k", now=0.0) is True
    assert limiter.allow("k", now=0.0) is True
    assert limiter.allow("k", now=0.0) is False
    assert limiter.allow("k", now=1.0) is True
    assert limiter.retry_after("k", now=1.1) >= 1


def test_has_tokens_peeks_without_consuming() -> None:
    limiter = TokenBucketLimiter(capacity=1, refill=1.0, window=1.0)
    assert limiter.has_tokens("k", now=0.0) is True
    assert limiter.allow("k", now=0.0) is True
    assert limiter.has_tokens("k", now=0.0) is False
    assert limiter.has_tokens("k", now=1.0) is True


def test_max_keys_evicts_least_recently_used() -> None:
    limiter = TokenBucketLimiter(capacity=1, refill=1.0, window=1.0, max_keys=2)
    assert limiter.allow("a", now=0.0) is True
    assert limiter.allow("b", now=0.0) is True
    assert limiter.allow("c", now=0.0) is True  # evicts the LRU key "a"
    assert len(limiter._updated) == 2
    assert "a" not in limiter._updated
    # the evicted key starts fresh (decision-neutral: it had refilled by now)
    assert limiter.has_tokens("a", now=0.0) is True


def test_max_keys_eviction_protects_a_recently_used_key() -> None:
    limiter = TokenBucketLimiter(capacity=2, refill=1.0, window=1.0, max_keys=2)
    assert limiter.allow("a", now=0.0) is True
    assert limiter.allow("b", now=0.0) is True
    assert limiter.allow("a", now=0.0) is True  # "a" becomes most-recently-used
    assert limiter.allow("c", now=0.0) is True  # evicts the LRU key "b", not "a"
    assert "b" not in limiter._updated
    assert "a" in limiter._updated and "c" in limiter._updated


def test_evict_stale_drops_fully_refilled_buckets() -> None:
    limiter = TokenBucketLimiter(capacity=1, refill=1.0, window=1.0)
    assert limiter.allow("k", now=100.0) is True
    assert limiter.evict_stale(now=100.5) == 0  # too recent
    assert limiter.evict_stale(now=101.0) == 1  # refilled → decision-neutral drop
    assert limiter.has_tokens("k", now=101.0) is True


def test_invalid_parameters_are_rejected() -> None:
    with pytest.raises(ValueError):
        TokenBucketLimiter(capacity=0, refill=1.0)
    with pytest.raises(ValueError):
        TokenBucketLimiter(capacity=1, refill=0.0)
    with pytest.raises(ValueError):
        TokenBucketLimiter(capacity=1, refill=1.0, max_keys=0)
