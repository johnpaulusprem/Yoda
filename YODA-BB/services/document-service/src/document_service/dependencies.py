"""Dependency injection -- DB sessions, RAG singletons for document service.

Provides lazy-initialized singletons for embedder, vector store, chunker,
retriever, and ingestion pipeline. Each ``get_*`` function creates its
singleton on first call using application settings.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from document_service.config import Settings

logger = logging.getLogger(__name__)

_engine = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None

# RAG singletons (lazy-initialised via get_* helpers)
_embedder: Any = None
_vector_store: Any = None
_chunker: Any = None
_retriever: Any = None
_ingestion_pipeline: Any = None
_document_classifier: Any = None


def init_db(settings: Settings) -> None:
    """Initialize the async SQLAlchemy engine and session factory.

    Must be called once at application startup (e.g. in ``lifespan``).
    """
    global _engine, _async_session_factory
    _engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        echo=settings.DEBUG,
    )
    _async_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, committing on success or rolling back on error."""
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
    """Return the cached application ``Settings`` singleton."""
    return Settings()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory (for services that manage their own sessions)."""
    if _async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _async_session_factory


def get_engine():
    """Return the async engine."""
    return _engine


def get_document_service(request: Request) -> Any:
    """FastAPI dependency that returns the DocumentService from app.state.

    Must be used with ``Depends()`` in route handlers.

    Args:
        request: The incoming FastAPI ``Request`` (injected automatically).

    Returns:
        The DocumentService instance stored on ``app.state``.

    Raises:
        RuntimeError: If DocumentService was not initialized at startup.
    """
    service = getattr(request.app.state, "document_service", None)
    if service is None:
        raise RuntimeError(
            "DocumentService not initialized. Ensure lifespan creates it."
        )
    return service


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
        )
    return _retriever


def get_document_classifier() -> Any:
    """Return the singleton DocumentClassifier instance.

    Uses the same embedder as the RAG pipeline. The classifier embeds
    templates on first use and caches them in memory.
    """
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
