"""Similarity-based retriever using embeddings and vector search."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from cxo_ai_companion.rag.embeddings.base_embedder import BaseEmbedder
from cxo_ai_companion.rag.retrieval.base_retriever import (
    BaseRetriever,
    RetrievalResult,
    RetrievedDocument,
)
from cxo_ai_companion.rag.vectorstore.base_vectorstore import (
    BaseVectorStore,
    VectorSearchResult,
)
from cxo_ai_companion.utilities.caching.cache import CacheInterface

logger = logging.getLogger(__name__)


@dataclass
class SimilarityRetrieverConfig:
    """Configuration for the similarity-based retriever.

    Attributes:
        top_k: Default number of results to return.
        score_threshold: Minimum similarity score to include a result.
        max_results: Hard upper limit on returned results.
    """

    top_k: int = 5
    score_threshold: float = 0.3
    max_results: int = 20


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

        logger.debug(
            "Embedding query for similarity retrieval (k=%d, threshold=%.2f)",
            effective_k,
            self._config.score_threshold,
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


__all__ = [
    "SimilarityRetriever",
    "SimilarityRetrieverConfig",
]
