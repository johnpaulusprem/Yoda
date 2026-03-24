"""LLM-based re-ranker for improving retrieval precision."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from yoda_foundation.dspy.adapters.llm_adapter import BaseLLMAdapter
from yoda_foundation.rag.retrieval.base_retriever import RetrievedDocument

logger = logging.getLogger(__name__)

_RERANK_SYSTEM_PROMPT = (
    "You are a relevance scoring assistant. Given a user query and a list of "
    "document excerpts, rate each excerpt's relevance to the query on a scale "
    "of 1 to 10 (1 = completely irrelevant, 10 = perfectly relevant). "
    "Respond ONLY with a JSON array of objects, each having 'index' (1-based) "
    "and 'score' (integer 1-10). No other text."
)


@dataclass
class RerankerConfig:
    """Configuration for the LLM re-ranker.

    Attributes:
        top_n: Maximum number of candidate documents to send to the LLM
            for scoring. Documents beyond this count are dropped.
        top_k: Number of highest-scored documents to return.
        max_content_chars: Maximum characters of each document to include
            in the scoring prompt.
        temperature: Sampling temperature for the scoring LLM call.
        fallback_on_error: If ``True``, return the original ranking when
            the LLM call or JSON parsing fails.
    """

    top_n: int = 15
    top_k: int = 5
    max_content_chars: int = 300
    temperature: float = 0.0
    fallback_on_error: bool = True


class LLMReranker:
    """Re-ranks retrieved documents using an LLM to score relevance.

    Takes the top-N candidates from retrieval, asks the LLM to score
    each chunk's relevance to the query on a 1-10 scale, then returns
    the top-K highest scored.

    Args:
        llm_adapter: LLM adapter for making scoring calls.
        config: Re-ranker configuration. Defaults to ``RerankerConfig()``.
    """

    def __init__(
        self,
        llm_adapter: BaseLLMAdapter,
        config: RerankerConfig | None = None,
    ) -> None:
        self._llm = llm_adapter
        self._config = config or RerankerConfig()

    async def rerank(
        self, query: str, documents: list[RetrievedDocument]
    ) -> list[RetrievedDocument]:
        """Score each document's relevance using the LLM and re-sort.

        If the document list is already shorter than ``top_k``, the
        documents are returned as-is without calling the LLM.

        Args:
            query: The user query to score against.
            documents: Retrieved documents to re-rank.

        Returns:
            A list of up to ``top_k`` documents sorted by LLM relevance score.
        """
        if len(documents) <= self._config.top_k:
            logger.debug(
                "Skipping rerank: %d docs <= top_k=%d",
                len(documents),
                self._config.top_k,
            )
            return documents

        candidates = documents[: self._config.top_n]

        prompt = self._build_scoring_prompt(query, candidates)

        try:
            response = await self._llm.call(
                prompt,
                system_prompt=_RERANK_SYSTEM_PROMPT,
                temperature=self._config.temperature,
            )
            scores = self._parse_scores(response.text, len(candidates))
        except Exception:
            logger.warning(
                "LLM reranking failed, %s",
                "returning original order" if self._config.fallback_on_error else "raising",
                exc_info=True,
            )
            if self._config.fallback_on_error:
                return documents[: self._config.top_k]
            raise

        # Pair candidates with their LLM scores and sort descending
        scored = []
        for idx, doc in enumerate(candidates):
            llm_score = scores.get(idx + 1, 0)
            scored.append((doc, llm_score))

        scored.sort(key=lambda pair: pair[1], reverse=True)

        result: list[RetrievedDocument] = []
        for rank, (doc, llm_score) in enumerate(scored[: self._config.top_k], start=1):
            result.append(
                RetrievedDocument(
                    id=doc.id,
                    content=doc.content,
                    score=llm_score / 10.0,  # Normalize 1-10 to 0-1
                    rank=rank,
                    metadata={**doc.metadata, "llm_rerank_score": llm_score},
                )
            )

        logger.info(
            "Re-ranked %d candidates to %d results (query=%r)",
            len(candidates),
            len(result),
            query[:80],
        )

        return result

    def _build_scoring_prompt(
        self, query: str, candidates: list[RetrievedDocument]
    ) -> str:
        """Build the relevance scoring prompt for the LLM.

        Args:
            query: The user query.
            candidates: Documents to be scored.

        Returns:
            The formatted prompt string.
        """
        parts = [f"Query: {query}", "", "Rate each document's relevance (1-10):", ""]

        for i, doc in enumerate(candidates, start=1):
            truncated = doc.content[: self._config.max_content_chars]
            if len(doc.content) > self._config.max_content_chars:
                truncated += "..."
            parts.append(f"[{i}] {truncated}")
            parts.append("")

        parts.append(
            'Respond ONLY with a JSON array: [{"index": 1, "score": 8}, ...]'
        )

        return "\n".join(parts)

    @staticmethod
    def _parse_scores(
        response_text: str, num_candidates: int
    ) -> dict[int, int]:
        """Parse the LLM's JSON response into a mapping of index to score.

        Performs defensive parsing: extracts the first JSON array found,
        validates each entry, and clamps scores to [1, 10].

        Args:
            response_text: Raw LLM response text.
            num_candidates: Expected number of candidates for bounds checking.

        Returns:
            A dict mapping 1-based document index to an integer score.
        """
        scores: dict[int, int] = {}

        # Find the first JSON array in the response
        text = response_text.strip()
        start_idx = text.find("[")
        end_idx = text.rfind("]")

        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            logger.warning("Could not find JSON array in reranker response")
            return scores

        json_str = text[start_idx : end_idx + 1]

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse reranker JSON: %r", json_str[:200])
            return scores

        if not isinstance(parsed, list):
            logger.warning("Reranker response is not a list")
            return scores

        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            idx = entry.get("index")
            score = entry.get("score")
            if (
                isinstance(idx, int)
                and isinstance(score, (int, float))
                and 1 <= idx <= num_candidates
            ):
                scores[idx] = max(1, min(10, int(score)))

        logger.debug("Parsed %d scores from reranker response", len(scores))
        return scores


__all__ = [
    "LLMReranker",
    "RerankerConfig",
]
