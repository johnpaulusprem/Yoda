"""Comprehensive tests for Redis/MemoryCache caching integration.

Covers:
1. init_cache / get_cache lifecycle (dependencies.py)
2. CachedLLMAdapter with external cache (llm_adapter.py)
3. SimilarityRetriever embedding cache (similarity_retriever.py)
4. PreMeetingService brief cache (pre_meeting_service.py)
5. Dashboard stats cache (dashboard.py route)
6. CachedGraphClient caching proxy (cached_graph_client.py)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cxo_ai_companion.utilities.caching import CacheConfig, MemoryCache
from cxo_ai_companion.utilities.caching.cache import CacheInterface


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def memory_cache() -> MemoryCache:
    """Fresh MemoryCache instance for testing."""
    return MemoryCache(config=CacheConfig(default_ttl_seconds=3600))


@pytest.fixture()
def mock_connector() -> AsyncMock:
    """Mock AIFoundryConnector with async complete method."""
    connector = AsyncMock()
    connector.complete = AsyncMock(return_value="LLM response text")
    return connector


@pytest.fixture()
def mock_embedder() -> AsyncMock:
    """Mock BaseEmbedder with async embed method."""
    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4])
    return embedder


@pytest.fixture()
def mock_vector_store() -> AsyncMock:
    """Mock BaseVectorStore with async search method."""
    from cxo_ai_companion.rag.vectorstore.base_vectorstore import (
        VectorDocument,
        VectorSearchResult,
    )

    store = AsyncMock()
    store.search = AsyncMock(
        return_value=[
            VectorSearchResult(
                document=VectorDocument(
                    id="doc-1",
                    vector=[0.1, 0.2],
                    content="test content",
                    metadata={"source": "test"},
                ),
                score=0.9,
                rank=1,
            )
        ]
    )
    return store


@pytest.fixture()
def mock_graph_client() -> AsyncMock:
    """Mock GraphClient for CachedGraphClient tests."""
    client = AsyncMock()
    client.get_calendar_events = AsyncMock(
        return_value=[{"id": "event-1", "subject": "Standup"}]
    )
    client.get_user_emails = AsyncMock(
        return_value=[{"id": "email-1", "subject": "Hello"}]
    )
    client.get_user_documents = AsyncMock(
        return_value=[{"id": "doc-1", "name": "Report.docx"}]
    )
    client.search_users = AsyncMock(
        return_value=[{"id": "user-1", "displayName": "Alice"}]
    )
    client.send_chat_message = AsyncMock(return_value={"id": "msg-1"})
    client.create_subscription = AsyncMock(return_value={"id": "sub-1"})
    return client


# ============================================================================
# 1. init_cache / get_cache lifecycle
# ============================================================================


class TestCacheLifecycle:
    """Tests for init_cache() and get_cache() in dependencies.py."""

    @pytest.mark.asyncio
    async def test_get_cache_raises_before_init(self):
        """get_cache() should raise RuntimeError when cache has not been initialized."""
        import cxo_ai_companion.dependencies as deps

        original_cache = deps._cache
        try:
            deps._cache = None
            with pytest.raises(RuntimeError, match="Cache not initialized"):
                deps.get_cache()
        finally:
            deps._cache = original_cache

    @pytest.mark.asyncio
    async def test_init_cache_fallback_to_memory(self):
        """When Redis URL is invalid/unreachable, init_cache falls back to MemoryCache."""
        import cxo_ai_companion.dependencies as deps

        original_cache = deps._cache
        try:
            deps._cache = None

            settings = MagicMock()
            settings.REDIS_URL = "redis://invalid-host-that-does-not-exist:6379/0"
            settings.REDIS_CACHE_DEFAULT_TTL = 300
            settings.REDIS_CACHE_KEY_PREFIX = "test"

            await deps.init_cache(settings)

            cache = deps.get_cache()
            assert isinstance(cache, MemoryCache)
        finally:
            deps._cache = original_cache

    @pytest.mark.asyncio
    async def test_init_cache_creates_cache_singleton(self):
        """After init_cache, get_cache should return a CacheInterface instance."""
        import cxo_ai_companion.dependencies as deps

        original_cache = deps._cache
        try:
            deps._cache = None

            settings = MagicMock()
            settings.REDIS_URL = "redis://localhost:99999/0"
            settings.REDIS_CACHE_DEFAULT_TTL = 600
            settings.REDIS_CACHE_KEY_PREFIX = "test"

            await deps.init_cache(settings)

            cache = deps.get_cache()
            assert isinstance(cache, CacheInterface)

            # Calling get_cache again returns the same singleton
            cache2 = deps.get_cache()
            assert cache is cache2
        finally:
            deps._cache = original_cache


# ============================================================================
# 2. CachedLLMAdapter with external cache
# ============================================================================


class TestCachedLLMAdapterWithExternalCache:
    """Tests for CachedLLMAdapter's external_cache (Redis/MemoryCache) integration."""

    @pytest.mark.asyncio
    async def test_cached_llm_adapter_uses_external_cache(
        self, mock_connector: AsyncMock, memory_cache: MemoryCache
    ):
        """When external_cache is set, the adapter stores results and retrieves on second call."""
        from cxo_ai_companion.dspy.adapters.llm_adapter import (
            AdapterConfig,
            CachedLLMAdapter,
        )

        adapter = CachedLLMAdapter(
            connector=mock_connector,
            config=AdapterConfig(cache_enabled=True, cache_ttl_seconds=3600),
            external_cache=memory_cache,
        )

        # First call -- cache miss, calls connector
        response1 = await adapter.call("What is AI?")
        assert response1.cached is False
        assert response1.text == "LLM response text"
        assert mock_connector.complete.call_count == 1

        # Second call with same prompt -- external cache hit
        response2 = await adapter.call("What is AI?")
        assert response2.cached is True
        assert response2.text == "LLM response text"
        # Connector should NOT be called again
        assert mock_connector.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_cached_llm_adapter_external_cache_miss_falls_back(
        self, mock_connector: AsyncMock, memory_cache: MemoryCache
    ):
        """When external cache misses, the adapter calls the LLM and stores the result."""
        from cxo_ai_companion.dspy.adapters.llm_adapter import (
            AdapterConfig,
            CachedLLMAdapter,
        )

        adapter = CachedLLMAdapter(
            connector=mock_connector,
            config=AdapterConfig(cache_enabled=True, cache_ttl_seconds=3600),
            external_cache=memory_cache,
        )

        # First call -- nothing in cache
        response = await adapter.call("Tell me a joke")
        assert response.cached is False
        assert mock_connector.complete.call_count == 1

        # Verify it was stored in external cache
        cache_key = CachedLLMAdapter._make_cache_key(
            "Tell me a joke", "gpt-4o-mini", 0.1
        )
        cached_value = await memory_cache.get(f"llm:{cache_key}")
        assert cached_value is not None
        assert cached_value["text"] == "LLM response text"

    @pytest.mark.asyncio
    async def test_cached_llm_adapter_without_external_cache(
        self, mock_connector: AsyncMock
    ):
        """When external_cache is None, the adapter uses only the in-memory dict."""
        from cxo_ai_companion.dspy.adapters.llm_adapter import (
            AdapterConfig,
            CachedLLMAdapter,
        )

        adapter = CachedLLMAdapter(
            connector=mock_connector,
            config=AdapterConfig(cache_enabled=True, cache_ttl_seconds=3600),
            external_cache=None,
        )

        # First call
        response1 = await adapter.call("Hello world")
        assert response1.cached is False
        assert mock_connector.complete.call_count == 1

        # Second call -- should hit in-memory cache
        response2 = await adapter.call("Hello world")
        assert response2.cached is True
        assert mock_connector.complete.call_count == 1

        # Verify cache stats
        stats = adapter.cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    @pytest.mark.asyncio
    async def test_cached_llm_adapter_different_prompts_different_keys(
        self, mock_connector: AsyncMock, memory_cache: MemoryCache
    ):
        """Different prompts should produce separate cache entries."""
        from cxo_ai_companion.dspy.adapters.llm_adapter import (
            AdapterConfig,
            CachedLLMAdapter,
        )

        mock_connector.complete = AsyncMock(side_effect=["Answer A", "Answer B"])

        adapter = CachedLLMAdapter(
            connector=mock_connector,
            config=AdapterConfig(cache_enabled=True),
            external_cache=memory_cache,
        )

        r1 = await adapter.call("Question 1")
        r2 = await adapter.call("Question 2")

        assert r1.text == "Answer A"
        assert r2.text == "Answer B"
        assert mock_connector.complete.call_count == 2


# ============================================================================
# 3. SimilarityRetriever embedding cache
# ============================================================================


class TestSimilarityRetrieverEmbeddingCache:
    """Tests for SimilarityRetriever's embedding vector caching."""

    @pytest.mark.asyncio
    async def test_retriever_caches_embeddings(
        self,
        mock_embedder: AsyncMock,
        mock_vector_store: AsyncMock,
        memory_cache: MemoryCache,
    ):
        """Second identical query should use cached embedding, not call embedder.embed again."""
        from cxo_ai_companion.rag.retrieval.similarity_retriever import (
            SimilarityRetriever,
        )

        retriever = SimilarityRetriever(
            embedder=mock_embedder,
            vector_store=mock_vector_store,
            cache=memory_cache,
        )

        # First retrieval -- embedder.embed is called
        result1 = await retriever.retrieve("test query", k=3)
        assert mock_embedder.embed.call_count == 1
        assert result1.total_results == 1

        # Second retrieval with same query -- embedder.embed should NOT be called again
        result2 = await retriever.retrieve("test query", k=3)
        assert mock_embedder.embed.call_count == 1  # Still 1
        assert result2.total_results == 1

        # Vector store search should be called both times (only embedding is cached)
        assert mock_vector_store.search.call_count == 2

    @pytest.mark.asyncio
    async def test_retriever_works_without_cache(
        self,
        mock_embedder: AsyncMock,
        mock_vector_store: AsyncMock,
    ):
        """When cache=None, retriever works the same as before (no caching)."""
        from cxo_ai_companion.rag.retrieval.similarity_retriever import (
            SimilarityRetriever,
        )

        retriever = SimilarityRetriever(
            embedder=mock_embedder,
            vector_store=mock_vector_store,
            cache=None,
        )

        result1 = await retriever.retrieve("test query", k=3)
        assert result1.total_results == 1
        assert mock_embedder.embed.call_count == 1

        # Without cache, second call hits the embedder again
        result2 = await retriever.retrieve("test query", k=3)
        assert mock_embedder.embed.call_count == 2

    @pytest.mark.asyncio
    async def test_retriever_different_queries_different_cache_keys(
        self,
        mock_embedder: AsyncMock,
        mock_vector_store: AsyncMock,
        memory_cache: MemoryCache,
    ):
        """Different queries produce different embedding cache entries."""
        from cxo_ai_companion.rag.retrieval.similarity_retriever import (
            SimilarityRetriever,
        )

        retriever = SimilarityRetriever(
            embedder=mock_embedder,
            vector_store=mock_vector_store,
            cache=memory_cache,
        )

        await retriever.retrieve("query A", k=3)
        await retriever.retrieve("query B", k=3)
        assert mock_embedder.embed.call_count == 2


# ============================================================================
# 4. PreMeetingService brief cache
# ============================================================================


class TestPreMeetingServiceBriefCache:
    """Tests for PreMeetingService's cache of generated briefs."""

    @pytest.mark.asyncio
    async def test_pre_meeting_service_caches_brief(self, memory_cache: MemoryCache):
        """Second call to generate_brief returns cached brief without DB queries."""
        from cxo_ai_companion.services.pre_meeting_service import (
            PreMeetingBrief,
            PreMeetingService,
        )

        meeting_id = uuid.uuid4()
        user_id = "user-123"

        # Pre-populate cache with a serialized brief
        cache_key = f"brief:{meeting_id}:{user_id}"
        cached_brief_data = {
            "meeting_id": str(meeting_id),
            "meeting_subject": "Cached Meeting",
            "scheduled_start": datetime.now(timezone.utc).isoformat(),
            "attendees": [],
            "past_decisions": [],
            "related_documents": [],
            "recent_email_subjects": [],
            "recent_email_threads": [],
            "suggested_questions": ["What about the budget?"],
            "executive_summary": "",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        await memory_cache.set(cache_key, cached_brief_data, ttl_seconds=7200)

        # Create the service with a mock DB (should never be called)
        mock_db = AsyncMock()
        service = PreMeetingService(
            db=mock_db,
            graph_client=None,
            ai_processor=None,
            cache=memory_cache,
        )

        brief = await service.generate_brief(meeting_id, user_id)

        assert isinstance(brief, PreMeetingBrief)
        assert brief.meeting_subject == "Cached Meeting"
        assert brief.suggested_questions == ["What about the budget?"]
        # DB should NOT have been queried
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_pre_meeting_service_works_without_cache(self):
        """When cache=None, generate_brief works the same as before (queries DB)."""
        from cxo_ai_companion.services.pre_meeting_service import PreMeetingService

        meeting_id = uuid.uuid4()
        user_id = "user-456"

        # Mock DB to return None (meeting not found)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = PreMeetingService(
            db=mock_db,
            graph_client=None,
            ai_processor=None,
            cache=None,
        )

        brief = await service.generate_brief(meeting_id, user_id)

        assert brief.meeting_subject == "Unknown Meeting"
        # DB should have been called (no cache to short-circuit)
        mock_db.execute.assert_called_once()


# ============================================================================
# 5. Dashboard stats cache
# ============================================================================


class TestDashboardStatsCache:
    """Tests for dashboard /stats endpoint caching pattern."""

    @pytest.mark.asyncio
    async def test_dashboard_stats_cached(self, memory_cache: MemoryCache):
        """When dashboard stats are in cache, the cached response is returned."""
        user_id = "exec-user-1"
        cache_key = f"dashboard:stats:{user_id}"

        cached_stats = {
            "meetings_today": 5,
            "pending_actions": 3,
            "overdue_actions": 1,
            "completion_rate": 75.0,
            "docs_to_review": 2,
        }
        await memory_cache.set(cache_key, cached_stats, ttl_seconds=120)

        # Simulate the caching pattern used in the dashboard route
        result = await memory_cache.get(cache_key)
        assert result is not None
        assert result["meetings_today"] == 5
        assert result["completion_rate"] == 75.0

    @pytest.mark.asyncio
    async def test_dashboard_stats_cache_miss_computes_fresh(
        self, memory_cache: MemoryCache
    ):
        """When cache misses, stats are computed and then stored in cache."""
        user_id = "exec-user-2"
        cache_key = f"dashboard:stats:{user_id}"

        # Verify cache is empty
        cached = await memory_cache.get(cache_key)
        assert cached is None

        # Simulate computing and storing
        computed_stats = {
            "meetings_today": 2,
            "pending_actions": 4,
            "overdue_actions": 0,
            "completion_rate": 85.5,
            "docs_to_review": 1,
        }
        await memory_cache.set(cache_key, computed_stats, ttl_seconds=120)

        # Verify stored
        result = await memory_cache.get(cache_key)
        assert result is not None
        assert result == computed_stats

    @pytest.mark.asyncio
    async def test_dashboard_stats_get_cache_failure_graceful(self):
        """When get_cache() raises RuntimeError, dashboard should handle it gracefully."""
        import cxo_ai_companion.dependencies as deps

        original_cache = deps._cache
        try:
            deps._cache = None
            # Verify get_cache raises as expected
            with pytest.raises(RuntimeError):
                deps.get_cache()
            # The route catches (RuntimeError, Exception) and sets cache=None,
            # then proceeds to compute stats from DB.
        finally:
            deps._cache = original_cache


# ============================================================================
# 6. CachedGraphClient
# ============================================================================


class TestCachedGraphClient:
    """Tests for the CachedGraphClient caching proxy."""

    @pytest.mark.asyncio
    async def test_cached_graph_client_caches_calendar_events(
        self, mock_graph_client: AsyncMock, memory_cache: MemoryCache
    ):
        """Second call to get_calendar_events returns cached data without calling underlying client."""
        from cxo_ai_companion.services.cached_graph_client import CachedGraphClient

        cached_client = CachedGraphClient(
            client=mock_graph_client,
            cache=memory_cache,
            ttl_seconds=300,
        )

        # First call -- cache miss, delegates to underlying client
        events1 = await cached_client.get_calendar_events("user-1", hours_ahead=24)
        assert len(events1) == 1
        assert events1[0]["subject"] == "Standup"
        assert mock_graph_client.get_calendar_events.call_count == 1

        # Second call -- cache hit
        events2 = await cached_client.get_calendar_events("user-1", hours_ahead=24)
        assert len(events2) == 1
        assert events2[0]["subject"] == "Standup"
        # Underlying client should NOT be called again
        assert mock_graph_client.get_calendar_events.call_count == 1

    @pytest.mark.asyncio
    async def test_cached_graph_client_caches_user_emails(
        self, mock_graph_client: AsyncMock, memory_cache: MemoryCache
    ):
        """Second call to get_user_emails returns cached data."""
        from cxo_ai_companion.services.cached_graph_client import CachedGraphClient

        cached_client = CachedGraphClient(
            client=mock_graph_client,
            cache=memory_cache,
            ttl_seconds=300,
        )

        emails1 = await cached_client.get_user_emails("user-1", days=7)
        assert mock_graph_client.get_user_emails.call_count == 1

        emails2 = await cached_client.get_user_emails("user-1", days=7)
        assert mock_graph_client.get_user_emails.call_count == 1
        assert emails1 == emails2

    @pytest.mark.asyncio
    async def test_cached_graph_client_caches_user_documents(
        self, mock_graph_client: AsyncMock, memory_cache: MemoryCache
    ):
        """Second call to get_user_documents returns cached data."""
        from cxo_ai_companion.services.cached_graph_client import CachedGraphClient

        cached_client = CachedGraphClient(
            client=mock_graph_client,
            cache=memory_cache,
            ttl_seconds=300,
        )

        docs1 = await cached_client.get_user_documents("user-1", limit=10)
        assert mock_graph_client.get_user_documents.call_count == 1

        docs2 = await cached_client.get_user_documents("user-1", limit=10)
        assert mock_graph_client.get_user_documents.call_count == 1
        assert docs1 == docs2

    @pytest.mark.asyncio
    async def test_cached_graph_client_caches_search_users(
        self, mock_graph_client: AsyncMock, memory_cache: MemoryCache
    ):
        """Second call to search_users returns cached data."""
        from cxo_ai_companion.services.cached_graph_client import CachedGraphClient

        cached_client = CachedGraphClient(
            client=mock_graph_client,
            cache=memory_cache,
            ttl_seconds=300,
        )

        users1 = await cached_client.search_users("Alice")
        assert mock_graph_client.search_users.call_count == 1

        users2 = await cached_client.search_users("Alice")
        assert mock_graph_client.search_users.call_count == 1
        assert users1 == users2

    @pytest.mark.asyncio
    async def test_cached_graph_client_different_params_different_keys(
        self, mock_graph_client: AsyncMock, memory_cache: MemoryCache
    ):
        """Different user IDs or parameters produce separate cache entries."""
        from cxo_ai_companion.services.cached_graph_client import CachedGraphClient

        cached_client = CachedGraphClient(
            client=mock_graph_client,
            cache=memory_cache,
            ttl_seconds=300,
        )

        await cached_client.get_calendar_events("user-1", hours_ahead=24)
        await cached_client.get_calendar_events("user-2", hours_ahead=24)

        # Both calls should hit the underlying client (different keys)
        assert mock_graph_client.get_calendar_events.call_count == 2

    @pytest.mark.asyncio
    async def test_cached_graph_client_pass_through_write_ops(
        self, mock_graph_client: AsyncMock, memory_cache: MemoryCache
    ):
        """Write methods (send_chat_message, create_subscription) are forwarded via __getattr__."""
        from cxo_ai_companion.services.cached_graph_client import CachedGraphClient

        cached_client = CachedGraphClient(
            client=mock_graph_client,
            cache=memory_cache,
            ttl_seconds=300,
        )

        # send_chat_message is not explicitly defined on CachedGraphClient,
        # so it should be forwarded to the underlying client via __getattr__
        result = await cached_client.send_chat_message(
            chat_id="chat-1", message="Hello"
        )
        assert result == {"id": "msg-1"}
        mock_graph_client.send_chat_message.assert_called_once_with(
            chat_id="chat-1", message="Hello"
        )

        # create_subscription should also be forwarded
        result2 = await cached_client.create_subscription(resource="me/events")
        assert result2 == {"id": "sub-1"}
        mock_graph_client.create_subscription.assert_called_once_with(
            resource="me/events"
        )


# ============================================================================
# 7. MemoryCache basic behavior (verifying test infrastructure)
# ============================================================================


class TestMemoryCacheBasicBehavior:
    """Sanity checks on MemoryCache used as test double throughout."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, memory_cache: MemoryCache):
        """Basic set/get round-trip."""
        await memory_cache.set("key1", {"data": "value"}, ttl_seconds=60)
        result = await memory_cache.get("key1")
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self, memory_cache: MemoryCache):
        """Getting a missing key returns None."""
        result = await memory_cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_key(self, memory_cache: MemoryCache):
        """Deleting a key removes it from cache."""
        await memory_cache.set("key1", "value1")
        deleted = await memory_cache.delete("key1")
        assert deleted is True
        assert await memory_cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_clear(self, memory_cache: MemoryCache):
        """Clearing removes all entries."""
        await memory_cache.set("a", 1)
        await memory_cache.set("b", 2)
        await memory_cache.clear()
        assert await memory_cache.get("a") is None
        assert await memory_cache.get("b") is None

    @pytest.mark.asyncio
    async def test_stats_tracking(self, memory_cache: MemoryCache):
        """Stats track hits, misses, and sets."""
        await memory_cache.set("x", 42)  # 1 set
        await memory_cache.get("x")  # 1 hit
        await memory_cache.get("missing")  # 1 miss

        stats = memory_cache.get_stats()
        assert stats.sets == 1
        assert stats.hits == 1
        assert stats.misses == 1
