"""Shared utilities for the cxo_ai_companion package.

Re-exports from the ``caching``, ``auth``, and ``retry`` submodules for
convenient top-level access::

    from cxo_ai_companion.utilities import MemoryCache, TokenProvider, with_retry
"""

from __future__ import annotations

# -- caching -----------------------------------------------------------------
from cxo_ai_companion.utilities.caching import (
    CacheConfig,
    CacheEntry,
    CacheInterface,
    CacheStats,
    MemoryCache,
    RedisCache,
    SerializerType,
)

# -- auth --------------------------------------------------------------------
from cxo_ai_companion.utilities.auth import TokenProvider

# -- retry -------------------------------------------------------------------
from cxo_ai_companion.utilities.retry import (
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
