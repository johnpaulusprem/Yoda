"""Hypothetical Document Embedding (HyDE) query expansion for RAG retrieval."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from yoda_foundation.dspy.adapters.llm_adapter import BaseLLMAdapter
from yoda_foundation.rag.embeddings.base_embedder import BaseEmbedder

logger = logging.getLogger(__name__)

_HYDE_SYSTEM_PROMPT = (
    "You are an expert technical writer. Your task is to write a short, "
    "factual paragraph that would directly answer the given question. "
    "Write as if you are quoting from an authoritative document. "
    "Be specific and concise (2-3 sentences). Do not include any preamble."
)


@dataclass
class QueryExpanderConfig:
    """Configuration for the HyDE query expander.

    Attributes:
        temperature: Sampling temperature for generating the hypothetical
            answer. Lower values produce more deterministic outputs.
        combination_strategy: How to combine the query and hypothetical
            embeddings. ``"average"`` takes the component-wise mean;
            ``"hyde_only"`` uses only the hypothetical answer embedding.
        enabled: Whether to actually perform expansion. When ``False``,
            the expander falls through to plain query embedding.
    """

    temperature: float = 0.3
    combination_strategy: str = "average"  # "average" or "hyde_only"
    enabled: bool = True


class QueryExpander:
    """Expands queries using HyDE (Hypothetical Document Embedding).

    Given a user question, generates a hypothetical short answer using
    an LLM, then embeds BOTH the question and the hypothetical answer.
    The retrieval uses the average (or HyDE-only) embedding for better
    semantic coverage.

    This technique is particularly effective when:
    - User queries are short or vague
    - The answer exists in documents using different terminology
    - The question is phrased differently from how the content is written

    Args:
        llm_adapter: LLM adapter for generating hypothetical answers.
        embedder: Embedding provider for vectorizing texts.
        config: Query expander configuration. Defaults to
            ``QueryExpanderConfig()``.
    """

    def __init__(
        self,
        llm_adapter: BaseLLMAdapter,
        embedder: BaseEmbedder,
        config: QueryExpanderConfig | None = None,
    ) -> None:
        self._llm = llm_adapter
        self._embedder = embedder
        self._config = config or QueryExpanderConfig()

    async def expand(self, query: str) -> list[float]:
        """Generate an expanded query embedding using HyDE.

        1. Ask the LLM to generate a hypothetical answer.
        2. Embed both the original query and the hypothetical answer.
        3. Combine the two embeddings according to ``combination_strategy``.

        If HyDE is disabled or generation fails, falls back to embedding
        the original query alone.

        Args:
            query: The user's natural-language question.

        Returns:
            A combined embedding vector suitable for vector similarity search.
        """
        if not self._config.enabled:
            logger.debug("HyDE disabled, embedding query directly")
            return await self._embedder.embed(query)

        try:
            hypothetical_answer = await self._generate_hypothetical(query)
        except Exception:
            logger.warning(
                "HyDE generation failed, falling back to plain query embedding",
                exc_info=True,
            )
            return await self._embedder.embed(query)

        logger.debug(
            "Generated hypothetical answer (%d chars) for query=%r",
            len(hypothetical_answer),
            query[:60],
        )

        # Embed both in parallel-safe manner
        query_vec = await self._embedder.embed(query)
        hyde_vec = await self._embedder.embed(hypothetical_answer)

        if self._config.combination_strategy == "hyde_only":
            logger.debug("Using HyDE-only embedding strategy")
            return hyde_vec

        # Default: average the two vectors
        combined = [
            (q + h) / 2.0 for q, h in zip(query_vec, hyde_vec)
        ]

        logger.debug(
            "Combined query + HyDE embeddings (dim=%d, strategy=%s)",
            len(combined),
            self._config.combination_strategy,
        )

        return combined

    async def _generate_hypothetical(self, query: str) -> str:
        """Generate a hypothetical document that would answer the query.

        Args:
            query: The user's question.

        Returns:
            A short hypothetical answer paragraph.

        Raises:
            ProgramExecutionError: If the LLM call fails.
        """
        prompt = (
            f"Write a short paragraph that would directly answer this question:\n"
            f"Question: {query}\n"
            f"Answer (2-3 sentences):"
        )

        response = await self._llm.call(
            prompt,
            system_prompt=_HYDE_SYSTEM_PROMPT,
            temperature=self._config.temperature,
        )

        return response.text.strip()


__all__ = [
    "QueryExpander",
    "QueryExpanderConfig",
]
