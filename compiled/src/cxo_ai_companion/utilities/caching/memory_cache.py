"""In-process async memory cache with LRU eviction.

Thread-safe via ``asyncio.Lock``.  Suitable for single-process deployments
or as a local L1 cache in front of a distributed backend.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from cxo_ai_companion.utilities.caching.cache import (
    CacheConfig,
    CacheEntry,
    CacheInterface,
    CacheStats,
)

logger = logging.getLogger(__name__)


class MemoryCache(CacheInterface):
    """Dict-backed async cache with LRU eviction and TTL expiry."""

    def __init__(self, config: CacheConfig | None = None) -> None:
        super().__init__(config)
        self._store: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    # -- helpers -------------------------------------------------------------

    def _evict_expired(self) -> None:
        """Remove all expired entries (caller must hold the lock)."""
        expired_keys = [k for k, v in self._store.items() if v.is_expired]
        for key in expired_keys:
            del self._store[key]
            if self.config.enable_stats:
                self._stats.evictions += 1

    def _evict_lru(self) -> None:
        """Evict the least-recently-used entry (caller must hold the lock)."""
        if not self._store:
            return
        lru_key = min(self._store, key=lambda k: self._store[k].last_accessed)
        del self._store[lru_key]
        if self.config.enable_stats:
            self._stats.evictions += 1

    def _ensure_capacity(self) -> None:
        """Evict entries until the store is within ``max_size``."""
        if self.config.max_size is None:
            return
        # First pass: remove anything already expired.
        self._evict_expired()
        # Second pass: LRU eviction if still over capacity.
        while len(self._store) >= self.config.max_size:
            self._evict_lru()

    # -- CacheInterface implementation ---------------------------------------

    async def get(self, key: str) -> Any | None:
        full_key = self._make_key(key)
        async with self._lock:
            entry = self._store.get(full_key)
            if entry is None:
                if self.config.enable_stats:
                    self._stats.misses += 1
                return None

            if entry.is_expired:
                del self._store[full_key]
                if self.config.enable_stats:
                    self._stats.misses += 1
                    self._stats.evictions += 1
                return None

            entry.mark_accessed()
            if self.config.enable_stats:
                self._stats.hits += 1
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        full_key = self._make_key(key)
        effective_ttl = ttl_seconds if ttl_seconds is not None else self.config.default_ttl_seconds

        entry = CacheEntry(
            value=value,
            ttl_seconds=effective_ttl,
            metadata=metadata or {},
        )

        async with self._lock:
            # If the key already exists we just overwrite; otherwise ensure room.
            if full_key not in self._store:
                self._ensure_capacity()
            self._store[full_key] = entry
            if self.config.enable_stats:
                self._stats.sets += 1
                self._stats.size = len(self._store)

    async def delete(self, key: str) -> bool:
        full_key = self._make_key(key)
        async with self._lock:
            if full_key in self._store:
                del self._store[full_key]
                if self.config.enable_stats:
                    self._stats.deletes += 1
                    self._stats.size = len(self._store)
                return True
            return False

    async def exists(self, key: str) -> bool:
        full_key = self._make_key(key)
        async with self._lock:
            entry = self._store.get(full_key)
            if entry is None:
                return False
            if entry.is_expired:
                del self._store[full_key]
                if self.config.enable_stats:
                    self._stats.evictions += 1
                return False
            return True

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
            if self.config.enable_stats:
                self._stats.size = 0

    async def close(self) -> None:
        """No external resources to release for an in-memory cache."""
        await self.clear()
        logger.debug("MemoryCache closed.")

    def get_stats(self) -> CacheStats:
        """Return a snapshot with the live size."""
        self._stats.size = len(self._store)
        return self._stats
