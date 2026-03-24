"""Cache interface and shared types for the yoda_foundation caching layer.

Provides the abstract CacheInterface contract, configuration dataclasses,
cache entry wrapper, and statistics tracking used by all concrete
implementations (MemoryCache, RedisCache, etc.).
"""

from __future__ import annotations

import enum
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Serializer enum
# ---------------------------------------------------------------------------

class SerializerType(enum.Enum):
    """Supported serialization formats for cache values."""

    JSON = "json"
    PICKLE = "pickle"
    MSGPACK = "msgpack"


# ---------------------------------------------------------------------------
# CacheEntry
# ---------------------------------------------------------------------------

@dataclass
class CacheEntry:
    """Wrapper around a cached value that tracks TTL and access metadata."""

    value: Any
    ttl_seconds: int | None = None
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    hit_count: int = 0
    last_accessed: float = field(default_factory=time.time)

    # -- derived helpers -----------------------------------------------------

    @property
    def expires_at(self) -> float | None:
        """Absolute epoch timestamp when this entry expires, or ``None``."""
        if self.ttl_seconds is None:
            return None
        return self.created_at + self.ttl_seconds

    @property
    def is_expired(self) -> bool:
        """Return ``True`` when the entry has exceeded its TTL."""
        if self.ttl_seconds is None:
            return False
        return time.time() >= (self.created_at + self.ttl_seconds)

    @property
    def remaining_ttl(self) -> float | None:
        """Seconds remaining before expiry, or ``None`` if no TTL is set."""
        if self.ttl_seconds is None:
            return None
        remaining = (self.created_at + self.ttl_seconds) - time.time()
        return max(remaining, 0.0)

    def mark_accessed(self) -> None:
        """Record an access hit -- bumps the counter and timestamp."""
        self.hit_count += 1
        self.last_accessed = time.time()


# ---------------------------------------------------------------------------
# CacheConfig
# ---------------------------------------------------------------------------

@dataclass
class CacheConfig:
    """Configuration bag consumed by every cache implementation."""

    default_ttl_seconds: int = 300
    max_size: int | None = None
    serializer: SerializerType = SerializerType.JSON
    key_prefix: str = ""
    enable_stats: bool = True
    compression_enabled: bool = False
    compression_threshold_bytes: int = 1024


# ---------------------------------------------------------------------------
# CacheStats
# ---------------------------------------------------------------------------

@dataclass
class CacheStats:
    """Runtime statistics for a cache instance."""

    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    evictions: int = 0
    size: int = 0

    @property
    def total_requests(self) -> int:
        """Total get requests (hits + misses)."""
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """Fraction of gets that were hits (0.0 -- 1.0)."""
        total = self.total_requests
        if total == 0:
            return 0.0
        return self.hits / total

    @property
    def miss_rate(self) -> float:
        """Fraction of gets that were misses (0.0 -- 1.0)."""
        total = self.total_requests
        if total == 0:
            return 0.0
        return self.misses / total


# ---------------------------------------------------------------------------
# CacheInterface ABC
# ---------------------------------------------------------------------------

class CacheInterface(ABC):
    """Abstract base class that every cache backend must implement."""

    def __init__(self, config: CacheConfig | None = None) -> None:
        self.config = config or CacheConfig()
        self._stats = CacheStats()

    # -- abstract methods ----------------------------------------------------

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Retrieve a value by *key*, or ``None`` if missing / expired."""
        ...

    @abstractmethod
    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store *value* under *key* with an optional TTL override."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete *key*. Return ``True`` if the key existed."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return ``True`` if *key* is present and not expired."""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Remove **all** entries from the cache."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release underlying resources (connections, file handles, etc.)."""
        ...

    # -- concrete helpers ----------------------------------------------------

    async def get_or_set(
        self,
        key: str,
        default_factory: Any,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Return the cached value for *key*, computing it via
        *default_factory* on a miss and storing the result.

        *default_factory* may be a coroutine function or a plain callable.
        """
        value = await self.get(key)
        if value is not None:
            return value

        # Compute the default -- support both async and sync callables.
        import asyncio

        if asyncio.iscoroutinefunction(default_factory):
            value = await default_factory()
        elif callable(default_factory):
            value = default_factory()
        else:
            value = default_factory

        await self.set(key, value, ttl_seconds=ttl_seconds, metadata=metadata)
        return value

    def get_stats(self) -> CacheStats:
        """Return a snapshot of the current cache statistics."""
        return self._stats

    def _make_key(self, key: str) -> str:
        """Apply the configured key prefix."""
        if self.config.key_prefix:
            return f"{self.config.key_prefix}:{key}"
        return key
