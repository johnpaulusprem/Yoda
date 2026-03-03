"""Caching utilities for cxo_ai_companion.

Re-exports the public API so consumers can write::

    from cxo_ai_companion.utilities.caching import MemoryCache, CacheConfig
"""

from __future__ import annotations

from cxo_ai_companion.utilities.caching.cache import (
    CacheConfig,
    CacheEntry,
    CacheInterface,
    CacheStats,
    SerializerType,
)
from cxo_ai_companion.utilities.caching.memory_cache import MemoryCache
from cxo_ai_companion.utilities.caching.redis_cache import RedisCache

__all__ = [
    "CacheConfig",
    "CacheEntry",
    "CacheInterface",
    "CacheStats",
    "MemoryCache",
    "RedisCache",
    "SerializerType",
]
