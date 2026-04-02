"""Similarity-based retriever using embeddings and vector search."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from yoda_foundation.rag.embeddings.base_embedder import BaseEmbedder
from yoda_foundation.rag.retrieval.base_retriever import (
    BaseRetriever,
    RetrievalResult,
    RetrievedDocument,
)
from yoda_foundation.rag.vectorstore.base_vectorstore import (
    BaseVectorStore,
    VectorSearchResult,
)
from yoda_foundation.utils.caching.cache import CacheInterface

logger = logging.getLogger(__name__)

# Keyword patterns for metadata-aware query analysis
_RECENCY_KEYWORDS: tuple[str, ...] = (
    "recent",
    "latest",
    "this week",
    "today",
    "yesterday",
    "last meeting",
    "this morning",
    "last week",
)

_CONTENT_TYPE_MAP: dict[str, str] = {
    # Presentations
    "presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "slides": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "deck": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "powerpoint": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # Spreadsheets
    "spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "model": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    # Documents
    "document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # PDF
    "pdf": "application/pdf",
    # Email
    "email": "message/rfc822",
    "mail": "message/rfc822",
}


@dataclass
class SimilarityRetrieverConfig:
    """Configuration for the similarity-based retriever.

    Attributes:
        top_k: Default number of results to return.
        score_threshold: Minimum similarity score to include a result.
        max_results: Hard upper limit on returned results.
        enable_metadata_detection: Whether to auto-detect metadata filters
            from the query text (time, document type, meeting references).
        recency_days: Number of days to consider for recency-based filters.
    """

    top_k: int = 5
    score_threshold: float = 0.3
    max_results: int = 20
    enable_metadata_detection: bool = True
    recency_days: int = 7


class SimilarityRetriever(BaseRetriever):
    """Retriever that embeds the query and performs vector similarity search.

    Converts the query to an embedding vector, searches the vector store,
    filters results by a score threshold, and returns ranked documents.

    Args:
        embedder: Embedding provider used to vectorize the query.
        vector_store: Vector store to search against.
        config: Retriever configuration. Defaults to
            ``SimilarityRetrieverConfig()``.
    """

    def __init__(
        self,
        embedder: BaseEmbedder,
        vector_store: BaseVectorStore,
        config: SimilarityRetrieverConfig | None = None,
        cache: CacheInterface | None = None,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._config = config or SimilarityRetrieverConfig()
        self._cache = cache

    async def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        """Embed the query, search the vector store, and return filtered results.

        When ``enable_metadata_detection`` is set, the query text is analysed
        for time references, document type hints, and meeting mentions.
        Detected metadata filters are merged with any explicitly provided
        filters (explicit filters take precedence on key collision).

        Args:
            query: The search query string.
            k: Maximum number of documents to return.  Capped by
                :pyattr:`SimilarityRetrieverConfig.max_results`.
            filters: Optional metadata filters forwarded to the vector store.

        Returns:
            A :class:`RetrievalResult` with documents above the score threshold.
        """
        start = time.perf_counter()

        effective_k = min(k or self._config.top_k, self._config.max_results)

        # Auto-detect metadata filters from the query text
        if self._config.enable_metadata_detection:
            detected = self._analyze_query_filters(query)
            if detected:
                logger.debug("Auto-detected metadata filters: %s", detected)
                # Merge: explicit filters override auto-detected ones
                if filters is not None:
                    merged = {**detected, **filters}
                else:
                    merged = detected
                filters = merged

        logger.debug(
            "Embedding query for similarity retrieval (k=%d, threshold=%.2f, filters=%s)",
            effective_k,
            self._config.score_threshold,
            filters,
        )

        query_vector: list[float] | None = None
        emb_cache_key = f"emb:{hashlib.sha256(query.encode()).hexdigest()}"
        if self._cache is not None:
            try:
                cached_vector = await self._cache.get(emb_cache_key)
                if cached_vector is not None:
                    query_vector = cached_vector
                    logger.debug("Embedding cache hit for query=%r", query[:40])
            except Exception:
                logger.debug("Embedding cache get failed, computing fresh embedding")

        if query_vector is None:
            query_vector = await self._embedder.embed(query)
            if self._cache is not None:
                try:
                    await self._cache.set(emb_cache_key, query_vector, ttl_seconds=86400)
                except Exception:
                    logger.debug("Embedding cache set failed")

        search_results: list[VectorSearchResult] = await self._vector_store.search(
            query_vector=query_vector,
            k=effective_k,
            filters=filters,
        )

        documents: list[RetrievedDocument] = []
        rank = 1
        for result in search_results:
            if result.score < self._config.score_threshold:
                logger.debug(
                    "Dropping result %s with score %.4f (below threshold %.2f)",
                    result.document.id,
                    result.score,
                    self._config.score_threshold,
                )
                continue

            documents.append(
                RetrievedDocument(
                    id=result.document.id,
                    content=result.document.content,
                    score=result.score,
                    rank=rank,
                    metadata=result.document.metadata,
                )
            )
            rank += 1

        elapsed_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "Similarity retrieval completed: %d results in %.1f ms "
            "(query=%r, k=%d)",
            len(documents),
            elapsed_ms,
            query[:80],
            effective_k,
        )

        return RetrievalResult(
            documents=documents,
            query=query,
            total_results=len(documents),
            execution_time_ms=elapsed_ms,
        )

    def _analyze_query_filters(self, query: str) -> dict[str, Any]:
        """Extract metadata filters from the query text.

        Inspects the query for:
        - **Time references** (e.g. "recent", "today", "this week") --
          sets a ``recency`` filter with value ``"7d"`` indicating the
          search should prefer documents from the last N days.
        - **Document type hints** (e.g. "spreadsheet", "pptx", "slides") --
          sets a ``content_type`` filter with the corresponding MIME type.
        - **Meeting references** (e.g. "meeting about X", "standup") --
          sets a ``source_type`` filter to ``"meeting_transcript"`` when
          meeting-related keywords are detected.

        Args:
            query: The user's natural-language query.

        Returns:
            A dict of metadata key-value pairs to be used as vector-store
            filters. Empty if no patterns matched.
        """
        filters: dict[str, Any] = {}
        query_lower = query.lower()

        # 1. Time-based recency
        for keyword in _RECENCY_KEYWORDS:
            if keyword in query_lower:
                filters["recency"] = f"{self._config.recency_days}d"
                break

        # 2. Document type hints
        for keyword, content_type in _CONTENT_TYPE_MAP.items():
            if keyword in query_lower:
                filters["content_type"] = content_type
                break

        # 3. Meeting-related references
        meeting_keywords = (
            "meeting",
            "standup",
            "stand-up",
            "sync",
            "review meeting",
            "retro",
            "retrospective",
            "all-hands",
            "townhall",
        )
        for keyword in meeting_keywords:
            if keyword in query_lower:
                filters["source_type"] = "meeting_transcript"
                break

        return filters


__all__ = [
    "SimilarityRetriever",
    "SimilarityRetrieverConfig",
]
