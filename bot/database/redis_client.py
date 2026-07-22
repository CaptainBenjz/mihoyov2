"""Redis connection management (Upstash-compatible).

Wraps ``redis.asyncio`` with:
  * lazy, pooled connections (redis-py auto-reconnects on the next command after a drop),
  * a periodic health check so idle connections are validated,
  * built-in retry with exponential backoff on transient connection/timeout errors,
  * automatic TLS upgrade for Upstash ``redis://`` URLs (Upstash requires TLS),
  * a ``verify()`` used at startup to confirm the connection before the bot serves traffic.

All higher-level stores accept the underlying ``redis.asyncio.Redis`` client and wrap their
own operations in try/except so a Redis outage degrades gracefully instead of crashing.
"""

from __future__ import annotations

import redis.asyncio as redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError

from bot.utils.logging import get_logger

logger = get_logger(__name__)


def normalize_url(url: str) -> str:
    """Upgrade Upstash ``redis://`` URLs to TLS (``rediss://``).

    Upstash's Redis endpoint requires TLS; a plain ``redis://`` connection is closed by the
    server. Users may paste either form, so we normalize here.
    """
    if url.startswith("redis://") and "upstash.io" in url:
        return "rediss://" + url[len("redis://"):]
    return url


class RedisClient:
    """Owns the process-wide async Redis connection pool."""

    def __init__(self, url: str) -> None:
        self._url = normalize_url(url)
        self._redis: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        """Return the shared client, creating the pool on first access."""
        if self._redis is None:
            self._redis = redis.from_url(
                self._url,
                decode_responses=True,
                socket_connect_timeout=10,
                socket_timeout=10,
                socket_keepalive=True,
                health_check_interval=30,
                retry=Retry(ExponentialBackoff(cap=10, base=0.1), retries=3),
                retry_on_error=[RedisConnectionError, RedisTimeoutError],
            )
        return self._redis

    async def verify(self) -> bool:
        """Ping Redis to confirm connectivity. Returns False instead of raising."""
        try:
            pong = await self.client.ping()
            if pong:
                logger.info("Redis connection verified")
                return True
            logger.error("Redis PING returned a falsy response")
            return False
        except RedisError as exc:
            logger.error("Redis connection could not be verified: %s", exc)
            return False

    async def is_healthy(self) -> bool:
        """Lightweight health probe used by /stats. Never raises."""
        try:
            return bool(await self.client.ping())
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        """Close the pool on shutdown."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._redis = None
