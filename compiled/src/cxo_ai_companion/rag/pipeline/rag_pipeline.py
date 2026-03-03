"""RAG pipeline — retrieves context and generates answers with citations."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from cxo_ai_companion.dspy.modules.chain_of_thought import (
    ChainOfThought,
    ChainOfThoughtResult,
)
from cxo_ai_companion.rag.context.citation_tracker import (
    Citation,
    CitationTracker,
    SourceReference,
)
from cxo_ai_companion.rag.context.context_builder import ContextBuilder
from cxo_ai_companion.rag.retrieval.base_retriever import BaseRetriever, RetrievedDocument
from cxo_ai_companion.security.context import SecurityContext

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
        dspy_module: ChainOfThought,
        config: RAGConfig | None = None,
    ) -> None:
        """Initialize the RAG pipeline.

        Args:
            retriever: Strategy for fetching relevant document chunks.
            context_builder: Formatter that assembles chunks into LLM context.
            citation_tracker: Tracker for registering and resolving citations.
            dspy_module: Chain-of-Thought module for generating the answer.
            config: Pipeline configuration. Defaults to ``RAGConfig()``.
        """
        self._retriever = retriever
        self._context_builder = context_builder
        self._citation_tracker = citation_tracker
        self._dspy_module = dspy_module
        self._config = config or RAGConfig()

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

        # 1. Retrieve relevant chunks
        retrieval_start = time.perf_counter()
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

        # 4. Generate answer via DSPy Chain-of-Thought
        generation_start = time.perf_counter()
        cot_result: ChainOfThoughtResult = await self._dspy_module.forward(
            security_context=security_context,
            contexts=context.formatted_text,
            question=question,
        )
        generation_time_ms = (time.perf_counter() - generation_start) * 1000

        # 5. Extract answer and reasoning from the CoT result
        answer = cot_result.outputs.get("answer", cot_result.raw_response)
        confidence = cot_result.confidence
        rationale = cot_result.rationale
        reasoning_steps = cot_result.reasoning_steps

        logger.info(
            "Generated answer (%.1fms): confidence=%.2f, steps=%d",
            generation_time_ms,
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
