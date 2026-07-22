"""Async-friendly TTL cache for external API responses.

In-memory ``TTLCache`` today; the :class:`ResponseCache` interface is intentionally
narrow so a Redis-backed implementation can be dropped in later without touching callers.

Usage::

    cache = ResponseCache(ttl=300)
    data = await cache.get_or_set(("enka", uid), lambda: enka_client.fetch_showcase(uid))
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Hashable, TypeVar

from cachetools import TTLCache

T = TypeVar("T")

# A cache key is a tuple like ("enka", "901211014") or ("akasha", "901211014").
CacheKey = tuple[Hashable, ...]


class ResponseCache:
    """A thread/async-safe TTL cache with a coalescing ``get_or_set``."""

    def __init__(self, ttl: int = 300, maxsize: int = 1024) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = asyncio.Lock()

    def get(self, key: CacheKey) -> object | None:
        return self._cache.get(key)

    def set(self, key: CacheKey, value: object) -> None:
        self._cache[key] = value

    def invalidate(self, key: CacheKey) -> None:
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()

    async def get_or_set(self, key: CacheKey, factory: Callable[[], Awaitable[T]]) -> T:
        """Return a cached value, or compute + store it via the async ``factory``.

        The lock coalesces concurrent misses for the whole cache; simple and correct for
        a single-process bot. A finer per-key lock can replace it if contention appears.
        """
        cached = self._cache.get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        async with self._lock:
            # Re-check after acquiring the lock (another coroutine may have filled it).
            cached = self._cache.get(key)
            if cached is not None:
                return cached  # type: ignore[return-value]
            value = await factory()
            self._cache[key] = value
            return value
