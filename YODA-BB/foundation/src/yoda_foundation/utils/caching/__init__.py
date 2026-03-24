"""Caching utilities for yoda_foundation.

Re-exports the public API so consumers can write::

    from yoda_foundation.utils.caching import MemoryCache, CacheConfig
"""

from __future__ import annotations

from yoda_foundation.utils.caching.cache import (
    CacheConfig,
    CacheEntry,
    CacheInterface,
    CacheStats,
    SerializerType,
)
from yoda_foundation.utils.caching.memory_cache import MemoryCache
from yoda_foundation.utils.caching.redis_cache import RedisCache

__all__ = [
    "CacheConfig",
    "CacheEntry",
    "CacheInterface",
    "CacheStats",
    "MemoryCache",
    "RedisCache",
    "SerializerType",
]
