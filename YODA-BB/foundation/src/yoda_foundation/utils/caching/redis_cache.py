"""Redis-backed async cache implementation.

``redis`` is an **optional** dependency.  If the package is not installed the
module still imports cleanly -- instantiating ``RedisCache`` will raise a clear
``ImportError`` at construction time.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from yoda_foundation.utils.caching.cache import (
    CacheConfig,
    CacheInterface,
    CacheStats,
)

logger = logging.getLogger(__name__)

# Graceful import -- redis is optional.
try:
    import redis.asyncio as aioredis  # type: ignore[import-untyped]

    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False


class RedisCache(CacheInterface):
    """Async cache backed by Redis with JSON serialisation and TTL support."""

    def __init__(
        self,
        config: CacheConfig | None = None,
        *,
        redis_url: str = "redis://localhost:6379/0",
        redis_client: Any | None = None,
    ) -> None:
        if not _REDIS_AVAILABLE:
            raise ImportError(
                "The 'redis' package is required for RedisCache. "
                "Install it with: pip install redis[hiredis]"
            )

        super().__init__(config)
        self._redis_url = redis_url

        if redis_client is not None:
            self._client: aioredis.Redis = redis_client  # type: ignore[union-attr]
        else:
            self._client = aioredis.from_url(  # type: ignore[union-attr]
                redis_url,
                decode_responses=True,
            )

    # -- serialisation helpers -----------------------------------------------

    @staticmethod
    def _serialize(value: Any) -> str:
        """Serialise *value* to a JSON string for storage."""
        return json.dumps(value)

    @staticmethod
    def _deserialize(raw: str | None) -> Any | None:
        """Deserialise a JSON string back to a Python object."""
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to deserialize cached value; returning None.")
            return None

    # -- internal key helpers ------------------------------------------------

    def _meta_key(self, full_key: str) -> str:
        """Return the companion metadata key for *full_key*."""
        return f"{full_key}:__meta__"

    # -- CacheInterface implementation ---------------------------------------

    async def get(self, key: str) -> Any | None:
        full_key = self._make_key(key)
        try:
            raw: str | None = await self._client.get(full_key)
        except Exception:
            logger.exception("Redis GET failed for key=%s", full_key)
            if self.config.enable_stats:
                self._stats.misses += 1
            return None

        if raw is None:
            if self.config.enable_stats:
                self._stats.misses += 1
            return None

        if self.config.enable_stats:
            self._stats.hits += 1

        return self._deserialize(raw)

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        full_key = self._make_key(key)
        effective_ttl = ttl_seconds if ttl_seconds is not None else self.config.default_ttl_seconds
        serialized = self._serialize(value)

        try:
            if effective_ttl is not None and effective_ttl > 0:
                await self._client.setex(full_key, effective_ttl, serialized)
            else:
                await self._client.set(full_key, serialized)

            # Optionally store metadata alongside the value.
            if metadata:
                meta_payload = self._serialize(
                    {
                        "metadata": metadata,
                        "created_at": time.time(),
                    }
                )
                meta_key = self._meta_key(full_key)
                if effective_ttl is not None and effective_ttl > 0:
                    await self._client.setex(meta_key, effective_ttl, meta_payload)
                else:
                    await self._client.set(meta_key, meta_payload)

        except Exception:
            logger.exception("Redis SET failed for key=%s", full_key)
            return

        if self.config.enable_stats:
            self._stats.sets += 1

    async def delete(self, key: str) -> bool:
        full_key = self._make_key(key)
        try:
            count: int = await self._client.delete(full_key)
            # Also clean up metadata key.
            await self._client.delete(self._meta_key(full_key))
        except Exception:
            logger.exception("Redis DELETE failed for key=%s", full_key)
            return False

        if self.config.enable_stats and count > 0:
            self._stats.deletes += 1
        return count > 0

    async def exists(self, key: str) -> bool:
        full_key = self._make_key(key)
        try:
            return bool(await self._client.exists(full_key))
        except Exception:
            logger.exception("Redis EXISTS failed for key=%s", full_key)
            return False

    async def clear(self) -> None:
        """Flush keys matching the configured prefix, or FLUSHDB when no
        prefix is set.

        **WARNING**: ``FLUSHDB`` removes *all* keys in the current Redis
        database -- use a key prefix in shared environments.
        """
        try:
            if self.config.key_prefix:
                pattern = f"{self.config.key_prefix}:*"
                cursor: int | str = 0
                while True:
                    cursor, keys = await self._client.scan(
                        cursor=cursor, match=pattern, count=500
                    )
                    if keys:
                        await self._client.delete(*keys)
                    if cursor == 0:
                        break
            else:
                await self._client.flushdb()
        except Exception:
            logger.exception("Redis CLEAR failed.")

        if self.config.enable_stats:
            self._stats.size = 0

    async def close(self) -> None:
        """Close the underlying Redis connection pool."""
        try:
            await self._client.aclose()
        except Exception:
            logger.exception("Redis close failed.")
        logger.debug("RedisCache closed.")

    def get_stats(self) -> CacheStats:
        """Return locally tracked stats.

        For live server-side stats use :pymeth:`get_server_stats` instead.
        """
        return self._stats

    # -- Redis-specific extras -----------------------------------------------

    async def get_server_stats(self) -> dict[str, Any]:
        """Return a subset of the Redis ``INFO`` command output."""
        try:
            info: dict[str, Any] = await self._client.info("stats")  # type: ignore[assignment]
            return {
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "N/A"),
            }
        except Exception:
            logger.exception("Redis INFO failed.")
            return {}
