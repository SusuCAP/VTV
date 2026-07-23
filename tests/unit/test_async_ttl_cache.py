from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from vtv_schemas.cache import AsyncTTLCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_call_counter(return_value):
    """Return (async_fn, call_count_holder) where call_count_holder is a list."""
    count = [0]

    async def fn(*args, **kwargs):
        count[0] += 1
        return return_value

    return fn, count


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stores_and_returns_value():
    """Cache stores the result and returns it."""
    cache = AsyncTTLCache(ttl_seconds=30.0)
    fn, count = await _make_call_counter(["result"])
    wrapped = cache.cached(fn)

    result = await wrapped("key")
    assert result == ["result"]
    assert count[0] == 1


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_call():
    """Second call with the same args returns cached value without re-invoking fn."""
    cache = AsyncTTLCache(ttl_seconds=30.0)
    fn, count = await _make_call_counter(42)
    wrapped = cache.cached(fn)

    first = await wrapped("x")
    second = await wrapped("x")

    assert first == second == 42
    assert count[0] == 1  # fn called only once


@pytest.mark.asyncio
async def test_ttl_expiry_returns_fresh_value():
    """After TTL expires the backing function is called again."""
    cache = AsyncTTLCache(ttl_seconds=10.0)
    call_no = [0]

    async def fn():
        call_no[0] += 1
        return call_no[0]

    wrapped = cache.cached(fn)

    first = await wrapped()
    assert first == 1

    # Advance monotonic clock past TTL
    with patch("vtv_schemas.cache.time.monotonic", return_value=time.monotonic() + 20.0):
        second = await wrapped()

    assert second == 2
    assert call_no[0] == 2


@pytest.mark.asyncio
async def test_invalidate_all_clears_entries():
    """invalidate() with no args removes every entry and returns count."""
    cache = AsyncTTLCache(ttl_seconds=60.0)
    fn, _ = await _make_call_counter("v")
    wrapped = cache.cached(fn)

    await wrapped("a")
    await wrapped("b")

    stats_before = await cache.stats()
    assert stats_before["size"] == 2

    count = await cache.invalidate()
    assert count == 2

    stats_after = await cache.stats()
    assert stats_after["size"] == 0


@pytest.mark.asyncio
async def test_invalidate_prefix_clears_only_matching():
    """invalidate(prefix) removes only entries whose function name starts with prefix."""
    cache = AsyncTTLCache(ttl_seconds=60.0)

    async def list_projects():
        return []

    async def get_project():
        return {}

    w_list = cache.cached(list_projects)
    w_get = cache.cached(get_project)

    await w_list()
    await w_get()

    count = await cache.invalidate(prefix="list_")
    assert count == 1

    stats = await cache.stats()
    # get_project entry remains
    assert stats["size"] == 1


@pytest.mark.asyncio
async def test_stats_returns_correct_counts():
    """stats() reflects current size and active entry count."""
    cache = AsyncTTLCache(ttl_seconds=60.0)
    fn, _ = await _make_call_counter("ok")
    wrapped = cache.cached(fn)

    await wrapped("p1")
    await wrapped("p2")

    stats = await cache.stats()
    assert stats["size"] == 2
    assert stats["active"] == 2
    assert stats["ttl_seconds"] == 60.0


@pytest.mark.asyncio
async def test_max_size_evicts_oldest_entry():
    """When max_size is reached the entry with the earliest expiry is evicted."""
    cache = AsyncTTLCache(ttl_seconds=60.0, max_size=1)

    call_no = [0]

    async def fn(key: str):
        call_no[0] += 1
        return f"v{call_no[0]}"

    wrapped = cache.cached(fn)

    first = await wrapped("a")   # fills the single slot
    assert first == "v1"
    assert call_no[0] == 1

    # Adding "b" evicts "a"
    second = await wrapped("b")
    assert second == "v2"
    assert call_no[0] == 2

    # "a" was evicted so it must be re-fetched
    third = await wrapped("a")
    assert third == "v3"
    assert call_no[0] == 3


@pytest.mark.asyncio
async def test_concurrent_access_same_key():
    """Two concurrent tasks requesting the same key both receive the correct result."""
    cache = AsyncTTLCache(ttl_seconds=30.0)
    call_no = [0]

    async def slow_fn():
        call_no[0] += 1
        await asyncio.sleep(0)  # yield once
        return call_no[0]

    wrapped = cache.cached(slow_fn)

    # Fire two tasks simultaneously
    results = await asyncio.gather(wrapped(), wrapped())

    # Both results must be equal (whichever value was cached first)
    assert results[0] == results[1]
    # At least one call was made
    assert call_no[0] >= 1
