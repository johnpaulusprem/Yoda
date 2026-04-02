"""Hybrid retriever combining vector similarity with PostgreSQL full-text search."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker

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

logger = logging.getLogger(__name__)


@dataclass
class HybridRetrieverConfig:
    """Configuration for the hybrid retriever.

    Attributes:
        top_k: Default number of results to return.
        score_threshold: Minimum score to include a result.
        max_results: Hard upper limit on returned results.
        vector_weight: Weight for vector search in final scoring (0-1).
        fts_weight: Weight for full-text search in final scoring (0-1).
        rrf_k: Smoothing constant for Reciprocal Rank Fusion.
            Higher values produce more uniform blending of the two
            ranked lists.
        candidate_multiplier: How many candidates to fetch from each
            source relative to the requested ``k``.
        table_name: Name of the document_chunks table for FTS queries.
    """

    top_k: int = 5
    score_threshold: float = 0.2
    max_results: int = 20
    vector_weight: float = 1.0
    fts_weight: float = 1.0
    rrf_k: int = 60
    candidate_multiplier: int = 3
    table_name: str = "document_chunks"


class HybridRetriever(BaseRetriever):
    """Combines vector similarity search with PostgreSQL full-text search.

    Retrieves candidates from both sources, normalizes scores, and merges
    using Reciprocal Rank Fusion (RRF). This approach captures both
    semantic similarity (via embeddings) and exact keyword matches
    (via tsvector/tsquery).

    Args:
        embedder: Embedding provider used to vectorize the query.
        vector_store: Vector store to search against.
        session_factory: SQLAlchemy async session factory for full-text
            search queries.
        config: Hybrid retriever configuration. Defaults to
            ``HybridRetrieverConfig()``.
    """

    def __init__(
        self,
        embedder: BaseEmbedder,
        vector_store: BaseVectorStore,
        session_factory: async_sessionmaker,
        config: HybridRetrieverConfig | None = None,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._session_factory = session_factory
        self._config = config or HybridRetrieverConfig()

    async def retrieve(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        """Retrieve documents using both vector and full-text search.

        1. Embed the query and search the vector store.
        2. Run a PostgreSQL full-text search with ``plainto_tsquery``.
        3. Merge results using Reciprocal Rank Fusion.
        4. Return the top-k merged results above the score threshold.

        Args:
            query: The search query string.
            k: Maximum number of documents to return.
            filters: Optional metadata filters forwarded to the vector store.

        Returns:
            A :class:`RetrievalResult` with the merged document list.
        """
        start = time.perf_counter()

        effective_k = min(k or self._config.top_k, self._config.max_results)
        candidate_k = effective_k * self._config.candidate_multiplier

        logger.debug(
            "Hybrid retrieval starting (k=%d, candidate_k=%d)",
            effective_k,
            candidate_k,
        )

        # 1. Vector search
        query_vector = await self._embedder.embed(query)
        vector_results: list[VectorSearchResult] = await self._vector_store.search(
            query_vector=query_vector,
            k=candidate_k,
            filters=filters,
        )

        # 2. Full-text search via PostgreSQL tsvector
        fts_results = await self._full_text_search(query, k=candidate_k)

        # 3. Merge using Reciprocal Rank Fusion
        merged = self._reciprocal_rank_fusion(
            vector_results,
            fts_results,
            k=effective_k,
            rrf_k=self._config.rrf_k,
        )

        # 4. Filter by score threshold
        documents = [
            doc for doc in merged if doc.score >= self._config.score_threshold
        ]

        elapsed_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "Hybrid retrieval completed: %d results in %.1f ms "
            "(vector=%d, fts=%d, merged=%d, query=%r)",
            len(documents),
            elapsed_ms,
            len(vector_results),
            len(fts_results),
            len(merged),
            query[:80],
        )

        return RetrievalResult(
            documents=documents,
            query=query,
            total_results=len(documents),
            execution_time_ms=elapsed_ms,
        )

    async def _full_text_search(
        self, query: str, k: int
    ) -> list[RetrievedDocument]:
        """Search document_chunks using PostgreSQL ts_rank + plainto_tsquery.

        Args:
            query: The user query string.
            k: Maximum number of results to return.

        Returns:
            A list of :class:`RetrievedDocument` with FTS rank as the score.
        """
        stmt = sa_text(
            f"""
            SELECT id, content, metadata,
                   ts_rank(
                       to_tsvector('english', content),
                       plainto_tsquery('english', :query)
                   ) AS rank
            FROM {self._config.table_name}
            WHERE to_tsvector('english', content)
                  @@ plainto_tsquery('english', :query)
            ORDER BY rank DESC
            LIMIT :k
            """
        )

        results: list[RetrievedDocument] = []
        try:
            async with self._session_factory() as session:
                rows = await session.execute(stmt, {"query": query, "k": k})
                for rank_pos, row in enumerate(rows, start=1):
                    row_id, content, metadata, fts_rank = row
                    meta = metadata if isinstance(metadata, dict) else {}
                    results.append(
                        RetrievedDocument(
                            id=str(row_id),
                            content=content or "",
                            score=float(fts_rank),
                            rank=rank_pos,
                            metadata=meta,
                        )
                    )
        except Exception:
            logger.warning(
                "Full-text search failed, returning empty results",
                exc_info=True,
            )

        logger.debug("Full-text search returned %d results", len(results))
        return results

    def _reciprocal_rank_fusion(
        self,
        vector_results: list[VectorSearchResult],
        fts_results: list[RetrievedDocument],
        k: int = 5,
        rrf_k: int = 60,
    ) -> list[RetrievedDocument]:
        """Merge two ranked lists using Reciprocal Rank Fusion.

        RRF score for a document is:
            ``sum(weight / (rrf_k + rank))``
        across all ranked lists in which the document appears.

        Args:
            vector_results: Results from the vector similarity search.
            fts_results: Results from PostgreSQL full-text search.
            k: Number of top results to return.
            rrf_k: Smoothing constant (default 60, per the original RRF paper).

        Returns:
            A list of :class:`RetrievedDocument` sorted by combined RRF score.
        """
        scores: dict[str, float] = {}
        doc_map: dict[str, RetrievedDocument] = {}

        # Score vector results
        for rank, result in enumerate(vector_results, 1):
            doc_id = result.document.id
            scores[doc_id] = scores.get(doc_id, 0.0) + (
                self._config.vector_weight / (rrf_k + rank)
            )
            if doc_id not in doc_map:
                doc_map[doc_id] = RetrievedDocument(
                    id=doc_id,
                    content=result.document.content,
                    score=0.0,  # will be overwritten below
                    rank=0,
                    metadata=result.document.metadata,
                )

        # Score FTS results
        for rank, result in enumerate(fts_results, 1):
            doc_id = result.id
            scores[doc_id] = scores.get(doc_id, 0.0) + (
                self._config.fts_weight / (rrf_k + rank)
            )
            if doc_id not in doc_map:
                doc_map[doc_id] = RetrievedDocument(
                    id=doc_id,
                    content=result.content,
                    score=0.0,
                    rank=0,
                    metadata=result.metadata,
                )

        # Sort by combined RRF score descending
        sorted_ids = sorted(scores.keys(), key=lambda d: scores[d], reverse=True)

        merged: list[RetrievedDocument] = []
        for rank_pos, doc_id in enumerate(sorted_ids[:k], start=1):
            doc = doc_map[doc_id]
            doc.score = scores[doc_id]
            doc.rank = rank_pos
            merged.append(doc)

        return merged


__all__ = [
    "HybridRetriever",
    "HybridRetrieverConfig",
]
