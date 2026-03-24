"""Context builder that formats retrieved documents for LLM consumption."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from yoda_foundation.rag.retrieval.base_retriever import RetrievedDocument

logger = logging.getLogger(__name__)


@dataclass
class ContextChunk:
    """A single chunk of context prepared for the LLM prompt.

    Attributes:
        content: The text content of the chunk.
        source_id: Identifier of the source document.
        score: Relevance score from retrieval.
        citation_index: The citation number assigned to this chunk (1-based).
        metadata: Additional metadata from the source document.
    """

    content: str
    source_id: str
    score: float
    citation_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalContext:
    """The fully assembled context ready for injection into an LLM prompt.

    Attributes:
        formatted_text: The final formatted text containing all chunks with
            citation markers.
        chunks: The individual context chunks used to build the text.
        total_tokens_estimate: Estimated total token count of the formatted text.
        num_sources: Number of distinct source documents included.
    """

    formatted_text: str
    chunks: list[ContextChunk]
    total_tokens_estimate: int
    num_sources: int


@dataclass
class ContextConfig:
    """Configuration for context building.

    Attributes:
        max_context_tokens: Maximum estimated tokens for the assembled context.
        citation_style: Citation formatting style (currently only "numbered").
        include_metadata: Whether to include metadata in the formatted output.
        separator: String used to separate chunks in the formatted output.
    """

    max_context_tokens: int = 4000
    citation_style: str = "numbered"
    include_metadata: bool = True
    separator: str = "\n\n---\n\n"


class ContextBuilder:
    """Builds formatted context from retrieved documents for LLM prompts.

    Takes a list of :class:`RetrievedDocument` instances, assigns citation
    numbers, formats each chunk with ``[N]`` markers, estimates the token
    count, and returns a :class:`RetrievalContext`.
    """

    def __init__(self, config: ContextConfig | None = None) -> None:
        self._config = config or ContextConfig()

    def build(self, results: list[RetrievedDocument]) -> RetrievalContext:
        """Build a formatted context from a list of retrieved documents.

        Documents are included in order until the estimated token budget
        is exhausted.

        Args:
            results: Retrieved documents ordered by relevance.

        Returns:
            A :class:`RetrievalContext` containing the formatted text,
            individual chunks, and metadata.
        """
        chunks: list[ContextChunk] = []
        formatted_parts: list[str] = []
        running_tokens = 0

        for index, doc in enumerate(results, start=1):
            formatted = self._format_chunk(doc, index)
            chunk_tokens = self._estimate_tokens(formatted)

            if running_tokens + chunk_tokens > self._config.max_context_tokens:
                logger.debug(
                    "Token budget exhausted at chunk %d "
                    "(running=%d, chunk=%d, max=%d)",
                    index,
                    running_tokens,
                    chunk_tokens,
                    self._config.max_context_tokens,
                )
                break

            chunks.append(
                ContextChunk(
                    content=doc.content,
                    source_id=doc.id,
                    score=doc.score,
                    citation_index=index,
                    metadata=doc.metadata,
                )
            )
            formatted_parts.append(formatted)
            running_tokens += chunk_tokens

        formatted_text = self._config.separator.join(formatted_parts)

        context = RetrievalContext(
            formatted_text=formatted_text,
            chunks=chunks,
            total_tokens_estimate=running_tokens,
            num_sources=len(chunks),
        )

        logger.info(
            "Built context with %d sources (~%d tokens)",
            context.num_sources,
            context.total_tokens_estimate,
        )

        return context

    def _format_chunk(self, doc: RetrievedDocument, index: int) -> str:
        """Format a single retrieved document with its citation marker.

        Args:
            doc: The retrieved document to format.
            index: The 1-based citation index to assign.

        Returns:
            A formatted string with the citation marker and content.
        """
        parts: list[str] = [f"[{index}]"]

        if self._config.include_metadata and doc.metadata:
            source_label = doc.metadata.get("title") or doc.metadata.get("source", "")
            if source_label:
                parts.append(f"Source: {source_label}")

        parts.append(doc.content)

        return "\n".join(parts)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate (1 token ~= 4 characters).

        Args:
            text: Input text.

        Returns:
            Estimated token count.
        """
        return len(text) // 4


__all__ = [
    "ContextBuilder",
    "ContextConfig",
    "ContextChunk",
    "RetrievalContext",
]
