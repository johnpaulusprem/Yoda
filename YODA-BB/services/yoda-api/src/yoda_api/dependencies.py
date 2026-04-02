"""Unified dependency injection -- DB sessions, RAG singletons, cache.

Merges dependencies from all former microservices. Provides lazy-initialized
singletons for embedder, vector store, chunker, retriever, ingestion pipeline,
document classifier, LLM adapter, RAG pipeline, and cache.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yoda_api.config import Settings

logger = logging.getLogger(__name__)

_engine = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None

# RAG + DSPy singletons (lazy-initialised via get_* helpers)
_embedder: Any = None
_vector_store: Any = None
_chunker: Any = None
_retriever: Any = None
_context_builder: Any = None
_rag_pipeline: Any = None
_llm_adapter: Any = None
_ingestion_pipeline: Any = None
_document_classifier: Any = None
_cache: Any = None


def init_db(settings: Settings) -> None:
    """Initialize the async SQLAlchemy engine and session factory."""
    global _engine, _async_session_factory
    _engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        echo=settings.DEBUG,
    )
    _async_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, committing on success or rolling back."""
    if _async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@functools.lru_cache
def get_settings() -> Settings:
    """Return the cached application Settings singleton."""
    return Settings()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory."""
    if _async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _async_session_factory


def get_engine():
    """Return the async engine."""
    return _engine


# ─── Cache ──────────────────────────────────────────────────────────────

async def init_cache(settings: Settings) -> None:
    """Initialize Redis cache. Falls back to MemoryCache if Redis unavailable."""
    global _cache
    try:
        from yoda_foundation.utils.caching import RedisCache, CacheConfig

        _cache = RedisCache(
            config=CacheConfig(
                default_ttl_seconds=settings.REDIS_CACHE_DEFAULT_TTL,
                key_prefix=settings.REDIS_CACHE_KEY_PREFIX,
            ),
            redis_url=settings.REDIS_URL,
        )
        await _cache._client.ping()
        logger.info("Redis cache initialized at %s", settings.REDIS_URL)
    except Exception as exc:
        logger.warning("Redis unavailable (%s), falling back to MemoryCache", exc)
        from yoda_foundation.utils.caching import MemoryCache, CacheConfig

        _cache = MemoryCache(
            config=CacheConfig(
                default_ttl_seconds=settings.REDIS_CACHE_DEFAULT_TTL,
                key_prefix=settings.REDIS_CACHE_KEY_PREFIX,
                max_size=1000,
            )
        )


def get_cache() -> Any:
    """Return the cache singleton."""
    if _cache is None:
        raise RuntimeError("Cache not initialized. Call init_cache() first.")
    return _cache


# ─── Document Service accessor ──────────────────────────────────────────

def get_document_service(request: Request) -> Any:
    """FastAPI dependency returning DocumentService from app.state."""
    service = getattr(request.app.state, "document_service", None)
    if service is None:
        raise RuntimeError("DocumentService not initialized.")
    return service


# ─── RAG Singletons ─────────────────────────────────────────────────────

def get_embedder() -> Any:
    """Return the singleton AzureEmbedder instance."""
    global _embedder
    if _embedder is None:
        from yoda_foundation.rag.embeddings.azure_embedder import (
            AzureEmbedder,
            AzureEmbedderConfig,
        )

        settings = get_settings()
        config = AzureEmbedderConfig(
            model_name=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            dimensions=settings.EMBEDDING_DIMENSIONS,
            azure_endpoint=settings.AZURE_OPENAI_EMBEDDING_ENDPOINT,
            api_key=settings.AZURE_OPENAI_EMBEDDING_KEY,
            deployment_name=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        )
        _embedder = AzureEmbedder(config)
    return _embedder


def get_vector_store() -> Any:
    """Return the singleton PGVectorStore instance."""
    global _vector_store
    if _vector_store is None:
        from yoda_foundation.rag.vectorstore.pgvector_store import (
            PGVectorConfig,
            PGVectorStore,
        )

        settings = get_settings()
        config = PGVectorConfig(dimensions=settings.EMBEDDING_DIMENSIONS)
        _vector_store = PGVectorStore(
            session_factory=get_session_factory(),
            config=config,
        )
    return _vector_store


def get_chunker() -> Any:
    """Return the singleton RecursiveChunker instance."""
    global _chunker
    if _chunker is None:
        from yoda_foundation.rag.chunking.recursive_chunker import (
            RecursiveChunker,
            RecursiveChunkerConfig,
        )

        settings = get_settings()
        config = RecursiveChunkerConfig(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )
        _chunker = RecursiveChunker(config)
    return _chunker


def get_retriever() -> Any:
    """Return the singleton SimilarityRetriever instance."""
    global _retriever
    if _retriever is None:
        from yoda_foundation.rag.retrieval.similarity_retriever import (
            SimilarityRetriever,
        )

        _retriever = SimilarityRetriever(
            embedder=get_embedder(),
            vector_store=get_vector_store(),
            cache=_cache,
        )
    return _retriever


def get_document_classifier() -> Any:
    """Return the singleton DocumentClassifier instance."""
    global _document_classifier
    if _document_classifier is None:
        from yoda_foundation.rag.classification.document_classifier import (
            DocumentClassifier,
        )

        _document_classifier = DocumentClassifier(
            embedder=get_embedder(),
            similarity_threshold=0.3,
        )
    return _document_classifier


def get_ingestion_pipeline() -> Any:
    """Return the singleton IngestionPipeline instance."""
    global _ingestion_pipeline
    if _ingestion_pipeline is None:
        from yoda_foundation.rag.pipeline.ingestion_pipeline import (
            IngestionPipeline,
        )

        _ingestion_pipeline = IngestionPipeline(
            chunker=get_chunker(),
            embedder=get_embedder(),
            vector_store=get_vector_store(),
        )
    return _ingestion_pipeline


def get_context_builder() -> Any:
    """Return the singleton ContextBuilder instance."""
    global _context_builder
    if _context_builder is None:
        from yoda_foundation.rag.context.context_builder import ContextBuilder

        _context_builder = ContextBuilder()
    return _context_builder


def get_citation_tracker() -> Any:
    """Return a new CitationTracker (stateful per-request, not a singleton)."""
    from yoda_foundation.rag.context.citation_tracker import CitationTracker

    return CitationTracker()


def get_llm_adapter() -> Any:
    """Return the singleton CachedLLMAdapter (or LLMAdapter) instance."""
    global _llm_adapter
    if _llm_adapter is None:
        from yoda_foundation.data_access.connectors.ai_foundry_connector import (
            AIFoundryConnector,
        )
        from yoda_foundation.data_access.base.connector import ConnectorConfig
        from yoda_foundation.dspy.adapters.llm_adapter import (
            AdapterConfig,
            CachedLLMAdapter,
            LLMAdapter,
        )

        settings = get_settings()
        connector_config = ConnectorConfig(name="ai-foundry-dspy")
        connector = AIFoundryConnector(
            config=connector_config,
            endpoint=settings.AI_FOUNDRY_ENDPOINT,
            api_key=settings.AI_FOUNDRY_API_KEY,
        )
        adapter_config = AdapterConfig(
            cache_enabled=settings.DSPY_CACHE_ENABLED,
            cache_ttl_seconds=settings.DSPY_CACHE_TTL,
        )
        if settings.DSPY_CACHE_ENABLED:
            _llm_adapter = CachedLLMAdapter(connector, adapter_config, external_cache=_cache)
        else:
            _llm_adapter = LLMAdapter(connector, adapter_config)
    return _llm_adapter


def get_rag_pipeline() -> Any:
    """Return the singleton RAGPipeline instance."""
    global _rag_pipeline
    if _rag_pipeline is None:
        from yoda_foundation.dspy.modules.chain_of_thought import ChainOfThought
        from yoda_foundation.dspy.signatures.rag_signatures import ContextualQA
        from yoda_foundation.rag.pipeline.rag_pipeline import RAGPipeline

        dspy_module = ChainOfThought(
            signature=ContextualQA,
            adapter=get_llm_adapter(),
        )
        _rag_pipeline = RAGPipeline(
            retriever=get_retriever(),
            context_builder=get_context_builder(),
            citation_tracker=get_citation_tracker(),
            dspy_module=dspy_module,
        )
    return _rag_pipeline
