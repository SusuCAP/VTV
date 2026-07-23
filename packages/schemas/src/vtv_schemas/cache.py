from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl_seconds: float):
        self.value = value
        self.expires_at = time.monotonic() + ttl_seconds


class AsyncTTLCache:
    """In-process async-safe TTL cache for idempotent read operations.

    Usage:
        cache = AsyncTTLCache(ttl_seconds=30)

        @cache.cached
        async def expensive_query(key: str) -> list[dict]:
            ...
    """

    def __init__(self, ttl_seconds: float = 30.0, max_size: int = 256):
        self._store: dict[tuple, CacheEntry] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._lock = asyncio.Lock()

    def cached(self, func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            key = (func.__name__, args, tuple(sorted(kwargs.items())))
            async with self._lock:
                entry = self._store.get(key)
                if entry and time.monotonic() < entry.expires_at:
                    return entry.value
            result = await func(*args, **kwargs)
            async with self._lock:
                if len(self._store) >= self._max_size:
                    # Evict oldest
                    oldest = min(self._store, key=lambda k: self._store[k].expires_at)
                    del self._store[oldest]
                self._store[key] = CacheEntry(result, self._ttl)
            return result

        return wrapper

    async def invalidate(self, prefix: str | None = None) -> int:
        """Invalidate all entries (or entries matching function name prefix)."""
        async with self._lock:
            if prefix is None:
                count = len(self._store)
                self._store.clear()
                return count
            to_delete = [k for k in self._store if k[0].startswith(prefix)]
            for k in to_delete:
                del self._store[k]
            return len(to_delete)

    async def stats(self) -> dict:
        """Return cache statistics."""
        async with self._lock:
            now = time.monotonic()
            active = sum(1 for e in self._store.values() if now < e.expires_at)
            return {"size": len(self._store), "active": active, "ttl_seconds": self._ttl}
