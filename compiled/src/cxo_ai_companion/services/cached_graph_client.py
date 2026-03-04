"""Caching wrapper for GraphClient — checks cache before delegating to Graph API."""

from __future__ import annotations

import logging
from typing import Any

from cxo_ai_companion.services.graph_client import GraphClient
from cxo_ai_companion.security.context import SecurityContext
from cxo_ai_companion.utilities.caching.cache import CacheInterface

logger = logging.getLogger(__name__)


class CachedGraphClient:
    """Thin caching proxy around :class:`GraphClient`.

    Caches read-only Graph API responses (calendar events, emails, documents,
    user search) with configurable TTL.  Write operations (subscriptions,
    messages) are forwarded directly without caching.

    Args:
        client: The underlying GraphClient instance.
        cache: A CacheInterface implementation (Redis or Memory).
        ttl_seconds: Default TTL for cached responses (default 300s / 5 min).
    """

    def __init__(
        self,
        client: GraphClient,
        cache: CacheInterface,
        ttl_seconds: int = 300,
    ) -> None:
        self._client = client
        self._cache = cache
        self._ttl = ttl_seconds

    async def get_calendar_events(
        self,
        user_id: str,
        hours_ahead: int = 24,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        key = f"graph:calendar:{user_id}:{hours_ahead}"
        cached = await self._safe_get(key)
        if cached is not None:
            return cached
        result = await self._client.get_calendar_events(user_id, hours_ahead, ctx=ctx)
        await self._safe_set(key, result)
        return result

    async def get_user_emails(
        self,
        user_id: str,
        days: int = 7,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        key = f"graph:emails:{user_id}:{days}"
        cached = await self._safe_get(key)
        if cached is not None:
            return cached
        result = await self._client.get_user_emails(user_id, days, ctx=ctx)
        await self._safe_set(key, result)
        return result

    async def get_user_documents(
        self,
        user_id: str,
        limit: int = 10,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        key = f"graph:docs:{user_id}:{limit}"
        cached = await self._safe_get(key)
        if cached is not None:
            return cached
        result = await self._client.get_user_documents(user_id, limit, ctx=ctx)
        await self._safe_set(key, result)
        return result

    async def search_users(
        self,
        display_name: str,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        key = f"graph:search_users:{display_name}"
        cached = await self._safe_get(key)
        if cached is not None:
            return cached
        result = await self._client.search_users(display_name, ctx=ctx)
        await self._safe_set(key, result)
        return result

    # Pass-through for non-cacheable or write methods
    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    # -- internal helpers --

    async def _safe_get(self, key: str) -> Any | None:
        try:
            return await self._cache.get(key)
        except Exception:
            logger.debug("Graph cache get failed for key=%s", key)
            return None

    async def _safe_set(self, key: str, value: Any) -> None:
        try:
            await self._cache.set(key, value, ttl_seconds=self._ttl)
        except Exception:
            logger.debug("Graph cache set failed for key=%s", key)
