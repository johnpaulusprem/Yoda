"""RAG pipeline — retrieves context and generates answers with citations.

Supports two generation backends:

1. **Real DSPy** (recommended) -- pass a ``dspy.Module`` (e.g.
   :class:`~yoda_foundation.dspy.integration.YodaQA`) as
   ``dspy_native_module``.  The module is called synchronously via the
   ``dspy`` runtime.

2. **Legacy custom ChainOfThought** -- pass a
   :class:`~yoda_foundation.dspy.modules.chain_of_thought.ChainOfThought`
   as ``dspy_module``.  The module is awaited asynchronously.

When both are provided, the real DSPy path takes priority.  When neither
is provided, ``__init__`` raises ``ValueError``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from yoda_foundation.dspy.modules.chain_of_thought import (
    ChainOfThought,
    ChainOfThoughtResult,
)
from yoda_foundation.rag.context.citation_tracker import (
    Citation,
    CitationTracker,
    SourceReference,
)
from yoda_foundation.rag.context.context_builder import ContextBuilder
from yoda_foundation.rag.retrieval.base_retriever import BaseRetriever, RetrievedDocument
from yoda_foundation.security.context import SecurityContext

if TYPE_CHECKING:
    import dspy

    from yoda_foundation.rag.retrieval.query_expander import QueryExpander
    from yoda_foundation.rag.retrieval.reranker import LLMReranker

logger = logging.getLogger(__name__)


@dataclass
class RAGConfig:
    """Configuration for the RAG query pipeline.

    Attributes:
        top_k: Number of document chunks to retrieve per query.
        include_citations: Whether to track and resolve citations in the answer.
        max_context_tokens: Maximum estimated tokens for the assembled context.
        model: LLM model name used for answer generation.
        temperature: Sampling temperature for the generation step.
    """

    top_k: int = 5
    include_citations: bool = True
    max_context_tokens: int = 4000
    model: str = "gpt-4o"
    temperature: float = 0.3


@dataclass
class RAGResult:
    """Complete result from a RAG query including answer, sources, and timing.

    Attributes:
        answer: The generated natural-language answer.
        query: The original user question.
        sources: Retrieved document chunks used as context.
        citations: Resolved citation objects mapped from ``[N]`` markers.
        confidence: Optional confidence score from the LLM (0.0 to 1.0).
        rationale: Free-text reasoning produced by Chain-of-Thought.
        reasoning_steps: Individual reasoning steps extracted from the rationale.
        retrieval_time_ms: Time spent on the retrieval stage.
        generation_time_ms: Time spent on the LLM generation stage.
        total_time_ms: End-to-end wall-clock time.
    """

    answer: str
    query: str
    sources: list[RetrievedDocument]
    citations: list[Citation] = field(default_factory=list)
    confidence: float | None = None
    rationale: str = ""
    reasoning_steps: list[str] = field(default_factory=list)
    retrieval_time_ms: float = 0.0
    generation_time_ms: float = 0.0
    total_time_ms: float = 0.0


class RAGPipeline:
    """Retrieval-Augmented Generation pipeline.

    Orchestrates the full RAG flow:

    1. **Retrieve** — fetch relevant document chunks via a
       :class:`BaseRetriever`.
    2. **Build context** — assemble retrieved chunks into a prompt-ready
       context string via a :class:`ContextBuilder`.
    3. **Track citations** — register each source with a
       :class:`CitationTracker` for bibliography generation.
    4. **Generate** — call a :class:`ChainOfThought` DSPy module to produce
       a reasoned answer grounded in the retrieved context.
    5. **Resolve citations** — map inline citation markers in the answer
       back to their sources.
    """

    def __init__(
        self,
        retriever: BaseRetriever,
        context_builder: ContextBuilder,
        citation_tracker: CitationTracker,
        dspy_module: ChainOfThought | None = None,
        config: RAGConfig | None = None,
        query_expander: QueryExpander | None = None,
        reranker: LLMReranker | None = None,
        dspy_native_module: dspy.Module | None = None,
    ) -> None:
        """Initialize the RAG pipeline.

        Args:
            retriever: Strategy for fetching relevant document chunks.
            context_builder: Formatter that assembles chunks into LLM context.
            citation_tracker: Tracker for registering and resolving citations.
            dspy_module: Legacy custom Chain-of-Thought module for generating
                the answer. Mutually exclusive with ``dspy_native_module``
                but at least one must be provided.
            config: Pipeline configuration. Defaults to ``RAGConfig()``.
            query_expander: Optional HyDE query expander. When provided,
                the query embedding is expanded before retrieval.
            reranker: Optional LLM re-ranker. When provided, retrieval
                results are re-ranked before context building.
            dspy_native_module: A real ``dspy.Module`` instance (e.g.
                :class:`~yoda_foundation.dspy.integration.YodaQA`).
                When provided this takes priority over ``dspy_module``.

        Raises:
            ValueError: If neither ``dspy_module`` nor
                ``dspy_native_module`` is supplied.
        """
        if dspy_module is None and dspy_native_module is None:
            raise ValueError(
                "RAGPipeline requires either 'dspy_module' (legacy) or "
                "'dspy_native_module' (real dspy). Neither was provided."
            )

        self._retriever = retriever
        self._context_builder = context_builder
        self._citation_tracker = citation_tracker
        self._dspy_module = dspy_module
        self._dspy_native_module = dspy_native_module
        self._use_real_dspy = dspy_native_module is not None
        self._config = config or RAGConfig()
        self._query_expander = query_expander
        self._reranker = reranker

    async def query(
        self,
        question: str,
        user_id: str | None = None,
        filters: dict[str, Any] | None = None,
        security_context: SecurityContext | None = None,
    ) -> RAGResult:
        """Execute a full RAG query.

        Args:
            question: The user's natural-language question.
            user_id: Optional user identifier for logging / filtering.
            filters: Optional metadata filters passed to the retriever.
            security_context: Optional security context for authorization.

        Returns:
            A :class:`RAGResult` containing the answer, sources, citations,
            reasoning, and timing information.
        """
        total_start = time.perf_counter()

        # 0. (Optional) Expand query using HyDE
        if self._query_expander is not None:
            try:
                logger.debug("Expanding query with HyDE: %r", question[:60])
                _expanded_vec = await self._query_expander.expand(question)
                # The expanded vector is used indirectly: pass the original
                # question to the retriever (which will embed it), but we
                # can store the expanded vector for hybrid search.
                # For now, HyDE is integrated by passing a hint via filters.
                if filters is None:
                    filters = {}
                filters["_hyde_vector"] = _expanded_vec
            except Exception:
                logger.warning(
                    "HyDE expansion failed, proceeding with original query",
                    exc_info=True,
                )

        # 1. Retrieve relevant chunks
        retrieval_start = time.perf_counter()

        # If we have a HyDE vector, use it directly with the vector store
        # when the retriever supports it; otherwise fall back to standard flow.
        hyde_vec = None
        if filters and "_hyde_vector" in filters:
            hyde_vec = filters.pop("_hyde_vector")

        if hyde_vec is not None and hasattr(self._retriever, "_vector_store"):
            # Direct vector search with the HyDE-expanded embedding
            from yoda_foundation.rag.retrieval.base_retriever import RetrievalResult
            from yoda_foundation.rag.vectorstore.base_vectorstore import VectorSearchResult

            search_results = await self._retriever._vector_store.search(
                query_vector=hyde_vec,
                k=self._config.top_k,
                filters=filters if filters else None,
            )
            documents: list[RetrievedDocument] = []
            for result in search_results:
                documents.append(
                    RetrievedDocument(
                        id=result.document.id,
                        content=result.document.content,
                        score=result.score,
                        rank=result.rank,
                        metadata=result.document.metadata,
                    )
                )
            retrieval_result = RetrievalResult(
                documents=documents,
                query=question,
                total_results=len(documents),
                execution_time_ms=(time.perf_counter() - retrieval_start) * 1000,
            )
        else:
            retrieval_result = await self._retriever.retrieve(
                query=question,
                k=self._config.top_k,
                filters=filters,
            )

        retrieval_time_ms = (time.perf_counter() - retrieval_start) * 1000

        logger.info(
            "Retrieved %d documents for query (%.1fms): %s",
            retrieval_result.total_results,
            retrieval_time_ms,
            question[:80],
        )

        # 1b. (Optional) Re-rank retrieved documents
        if self._reranker is not None and retrieval_result.documents:
            try:
                logger.debug(
                    "Re-ranking %d documents with LLM reranker",
                    len(retrieval_result.documents),
                )
                reranked = await self._reranker.rerank(
                    question, retrieval_result.documents
                )
                retrieval_result = RetrievalResult(
                    documents=reranked,
                    query=retrieval_result.query,
                    total_results=len(reranked),
                    execution_time_ms=retrieval_result.execution_time_ms,
                )
            except Exception:
                logger.warning(
                    "Re-ranking failed, using original retrieval order",
                    exc_info=True,
                )

        # 2. Build context from retrieved documents
        context = self._context_builder.build(retrieval_result.documents)

        # 3. Register sources with the citation tracker
        if self._config.include_citations:
            for doc in retrieval_result.documents:
                source_ref = SourceReference(
                    source_id=doc.id,
                    title=doc.metadata.get("title", doc.id),
                    url=doc.metadata.get("url"),
                    document_id=doc.metadata.get("document_id"),
                    chunk_index=doc.metadata.get("chunk_index"),
                    metadata=doc.metadata,
                )
                self._citation_tracker.add_source(source_ref)

        # 4. Generate answer
        generation_start = time.perf_counter()

        if self._use_real_dspy and self._dspy_native_module is not None:
            # ── Real DSPy path ─────────────────────────────────────────
            prediction = self._dspy_native_module(
                contexts=context.formatted_text,
                question=question,
            )
            generation_time_ms = (
                (time.perf_counter() - generation_start) * 1000
            )

            answer = prediction.answer
            confidence = (
                float(prediction.confidence)
                if hasattr(prediction, "confidence")
                else None
            )
            rationale = (
                prediction.reasoning
                if hasattr(prediction, "reasoning")
                else ""
            )
            # Real DSPy does not produce discrete reasoning_steps
            reasoning_steps: list[str] = []
        else:
            # ── Legacy custom ChainOfThought path ──────────────────────
            assert self._dspy_module is not None  # guaranteed by __init__
            cot_result: ChainOfThoughtResult = await self._dspy_module.forward(
                security_context=security_context,
                contexts=context.formatted_text,
                question=question,
            )
            generation_time_ms = (
                (time.perf_counter() - generation_start) * 1000
            )

            answer = cot_result.outputs.get("answer", cot_result.raw_response)
            confidence = cot_result.confidence
            rationale = cot_result.rationale
            reasoning_steps = cot_result.reasoning_steps

        logger.info(
            "Generated answer (%.1fms, real_dspy=%s): confidence=%.2f, steps=%d",
            generation_time_ms,
            self._use_real_dspy,
            confidence if confidence is not None else -1.0,
            len(reasoning_steps),
        )

        # 6. Resolve citations from the answer text
        citations: list[Citation] = []
        if self._config.include_citations:
            citations = self._citation_tracker.resolve_citations(answer)

        total_time_ms = (time.perf_counter() - total_start) * 1000

        return RAGResult(
            answer=answer,
            query=question,
            sources=retrieval_result.documents,
            citations=citations,
            confidence=confidence,
            rationale=rationale,
            reasoning_steps=reasoning_steps,
            retrieval_time_ms=retrieval_time_ms,
            generation_time_ms=generation_time_ms,
            total_time_ms=total_time_ms,
        )


__all__ = [
    "RAGConfig",
    "RAGPipeline",
    "RAGResult",
]
