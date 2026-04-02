"""Shared utilities for the yoda_foundation package.

Re-exports from the ``caching``, ``auth``, and ``retry`` submodules for
convenient top-level access::

    from yoda_foundation.utils import MemoryCache, TokenProvider, with_retry
"""

from __future__ import annotations

# -- caching -----------------------------------------------------------------
from yoda_foundation.utils.caching import (
    CacheConfig,
    CacheEntry,
    CacheInterface,
    CacheStats,
    MemoryCache,
    RedisCache,
    SerializerType,
)

# -- auth --------------------------------------------------------------------
from yoda_foundation.utils.auth import TokenProvider

# -- retry -------------------------------------------------------------------
from yoda_foundation.utils.retry import (
    RetryConfig,
    retry_context,
    with_retry,
    with_retry_sync,
)

__all__ = [
    # caching
    "CacheConfig",
    "CacheEntry",
    "CacheInterface",
    "CacheStats",
    "MemoryCache",
    "RedisCache",
    "SerializerType",
    # auth
    "TokenProvider",
    # retry
    "RetryConfig",
    "retry_context",
    "with_retry",
    "with_retry_sync",
]
