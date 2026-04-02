"""RAG pipeline evaluation framework for measuring retrieval and answer quality."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from yoda_foundation.dspy.adapters.llm_adapter import BaseLLMAdapter
from yoda_foundation.rag.pipeline.rag_pipeline import RAGPipeline, RAGResult

logger = logging.getLogger(__name__)

_RELEVANCE_SYSTEM_PROMPT = (
    "You are an expert evaluator. Given a question, an expected answer, and "
    "a generated answer, rate the generated answer's quality on a scale of "
    "0.0 to 1.0 (0 = completely wrong, 1 = perfect). Consider factual "
    "accuracy, completeness, and relevance. Respond with ONLY a single "
    "decimal number."
)

_FAITHFULNESS_SYSTEM_PROMPT = (
    "You are a faithfulness evaluator. Given a context (source documents) "
    "and a generated answer, determine whether the answer ONLY uses "
    "information present in the context. Rate faithfulness from 0.0 to 1.0 "
    "(0 = completely hallucinated, 1 = fully grounded in context). "
    "Respond with ONLY a single decimal number."
)


@dataclass
class EvalCase:
    """A single evaluation case.

    Attributes:
        question: The user question to ask the pipeline.
        expected_answer: The ground-truth answer for quality comparison.
        expected_sources: Document IDs or titles that should be retrieved.
        category: Category of the question (e.g. "factual", "reasoning",
            "multi-doc"). Used for per-category metric breakdowns.
    """

    question: str
    expected_answer: str
    expected_sources: list[str]
    category: str = "general"


@dataclass
class EvalMetrics:
    """Aggregated evaluation metrics across all test cases.

    Attributes:
        precision_at_k: Fraction of retrieved documents that are relevant,
            averaged across all cases.
        recall_at_k: Fraction of relevant documents that were retrieved,
            averaged across all cases.
        mrr: Mean Reciprocal Rank -- the average of ``1 / rank`` of the
            first relevant document across all cases.
        answer_relevance: LLM-judged answer quality averaged across cases
            (0.0 to 1.0). Set to 0.0 if no LLM judge is provided.
        faithfulness: LLM-judged faithfulness averaged across cases
            (0.0 to 1.0). Set to 0.0 if no LLM judge is provided.
        total_cases: Total number of evaluation cases processed.
        avg_retrieval_time_ms: Average retrieval latency in milliseconds.
        avg_total_time_ms: Average end-to-end query latency in milliseconds.
        per_category: Metric breakdown per question category.
    """

    precision_at_k: float
    recall_at_k: float
    mrr: float
    answer_relevance: float
    faithfulness: float
    total_cases: int
    avg_retrieval_time_ms: float = 0.0
    avg_total_time_ms: float = 0.0
    per_category: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class _CaseResult:
    """Internal per-case result used during aggregation."""

    precision: float
    recall: float
    reciprocal_rank: float
    relevance: float
    faithfulness: float
    retrieval_time_ms: float
    total_time_ms: float
    category: str


class RAGEvaluator:
    """Evaluates RAG pipeline accuracy against golden QA pairs.

    Runs each :class:`EvalCase` through the pipeline, computes retrieval
    metrics (Precision@K, Recall@K, MRR), and optionally uses an LLM
    judge to score answer relevance and faithfulness.

    Args:
        pipeline: The RAG pipeline to evaluate.
        llm_judge: Optional LLM adapter for scoring answer quality.
            When ``None``, answer_relevance and faithfulness are set to 0.0.
    """

    def __init__(
        self,
        pipeline: RAGPipeline,
        llm_judge: BaseLLMAdapter | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._judge = llm_judge

    async def evaluate(
        self, cases: list[EvalCase], k: int = 5
    ) -> EvalMetrics:
        """Run all eval cases through the pipeline and compute metrics.

        Args:
            cases: List of evaluation cases with expected answers and sources.
            k: The K value for Precision@K and Recall@K.

        Returns:
            Aggregated :class:`EvalMetrics` across all cases.
        """
        if not cases:
            return EvalMetrics(
                precision_at_k=0.0,
                recall_at_k=0.0,
                mrr=0.0,
                answer_relevance=0.0,
                faithfulness=0.0,
                total_cases=0,
            )

        results: list[_CaseResult] = []

        for i, case in enumerate(cases):
            logger.info(
                "Evaluating case %d/%d: %r (category=%s)",
                i + 1,
                len(cases),
                case.question[:60],
                case.category,
            )

            start = time.perf_counter()
            try:
                rag_result = await self._pipeline.query(question=case.question)
            except Exception:
                logger.error(
                    "Pipeline failed for case %d: %r",
                    i + 1,
                    case.question[:60],
                    exc_info=True,
                )
                results.append(
                    _CaseResult(
                        precision=0.0,
                        recall=0.0,
                        reciprocal_rank=0.0,
                        relevance=0.0,
                        faithfulness=0.0,
                        retrieval_time_ms=0.0,
                        total_time_ms=(time.perf_counter() - start) * 1000,
                        category=case.category,
                    )
                )
                continue

            elapsed_ms = (time.perf_counter() - start) * 1000

            # Extract retrieved document IDs and titles for matching
            retrieved_ids = self._extract_identifiers(rag_result)

            # Compute retrieval metrics
            precision = self._compute_precision_at_k(
                retrieved_ids, case.expected_sources, k
            )
            recall = self._compute_recall_at_k(
                retrieved_ids, case.expected_sources, k
            )
            mrr = self._compute_mrr(retrieved_ids, case.expected_sources)

            # Compute LLM-judged quality metrics
            relevance = 0.0
            faithfulness_score = 0.0
            if self._judge is not None:
                relevance = await self._judge_answer_relevance(
                    case.question, rag_result.answer, case.expected_answer
                )
                context_text = "\n\n".join(
                    doc.content for doc in rag_result.sources
                )
                faithfulness_score = await self._judge_faithfulness(
                    rag_result.answer, context_text
                )

            results.append(
                _CaseResult(
                    precision=precision,
                    recall=recall,
                    reciprocal_rank=mrr,
                    relevance=relevance,
                    faithfulness=faithfulness_score,
                    retrieval_time_ms=rag_result.retrieval_time_ms,
                    total_time_ms=elapsed_ms,
                    category=case.category,
                )
            )

        return self._aggregate(results)

    @staticmethod
    def _extract_identifiers(rag_result: RAGResult) -> list[str]:
        """Extract all identifiers (IDs and titles) from retrieved sources.

        This allows matching against expected_sources that may be specified
        as either document IDs or document titles.

        Args:
            rag_result: The RAG pipeline result.

        Returns:
            A flat list of identifiers for each retrieved document.
        """
        identifiers: list[str] = []
        for doc in rag_result.sources:
            identifiers.append(doc.id)
            title = doc.metadata.get("title", "")
            if title:
                identifiers.append(title)
        return identifiers

    @staticmethod
    def _compute_precision_at_k(
        retrieved_ids: list[str], relevant_ids: list[str], k: int
    ) -> float:
        """Compute Precision@K: fraction of top-K retrieved docs that are relevant.

        Args:
            retrieved_ids: List of retrieved document identifiers.
            relevant_ids: List of expected relevant document identifiers.
            k: The cutoff rank.

        Returns:
            Precision score between 0.0 and 1.0.
        """
        if k <= 0:
            return 0.0
        retrieved_set = set(retrieved_ids[:k])
        relevant_set = set(relevant_ids)
        hits = len(retrieved_set & relevant_set)
        return hits / k

    @staticmethod
    def _compute_recall_at_k(
        retrieved_ids: list[str], relevant_ids: list[str], k: int
    ) -> float:
        """Compute Recall@K: fraction of relevant docs that were retrieved.

        Args:
            retrieved_ids: List of retrieved document identifiers.
            relevant_ids: List of expected relevant document identifiers.
            k: The cutoff rank.

        Returns:
            Recall score between 0.0 and 1.0.
        """
        if not relevant_ids:
            return 0.0
        retrieved_set = set(retrieved_ids[:k])
        relevant_set = set(relevant_ids)
        hits = len(retrieved_set & relevant_set)
        return hits / len(relevant_set)

    @staticmethod
    def _compute_mrr(
        retrieved_ids: list[str], relevant_ids: list[str]
    ) -> float:
        """Compute Mean Reciprocal Rank for a single query.

        Returns ``1 / rank`` where rank is the position of the first
        relevant document found. Returns 0.0 if no relevant document
        is retrieved.

        Args:
            retrieved_ids: List of retrieved document identifiers.
            relevant_ids: List of expected relevant document identifiers.

        Returns:
            Reciprocal rank value between 0.0 and 1.0.
        """
        relevant_set = set(relevant_ids)
        for rank, doc_id in enumerate(retrieved_ids, 1):
            if doc_id in relevant_set:
                return 1.0 / rank
        return 0.0

    async def _judge_answer_relevance(
        self, question: str, answer: str, expected: str
    ) -> float:
        """Use LLM to judge answer quality on a 0-1 scale.

        Args:
            question: The original question.
            answer: The generated answer.
            expected: The expected ground-truth answer.

        Returns:
            A quality score between 0.0 and 1.0.
        """
        if self._judge is None:
            return 0.0

        prompt = (
            f"Question: {question}\n\n"
            f"Expected answer: {expected}\n\n"
            f"Generated answer: {answer}\n\n"
            f"Rate the generated answer's quality (0.0 to 1.0):"
        )

        try:
            response = await self._judge.call(
                prompt,
                system_prompt=_RELEVANCE_SYSTEM_PROMPT,
                temperature=0.0,
            )
            return self._parse_float_score(response.text)
        except Exception:
            logger.warning("Answer relevance judging failed", exc_info=True)
            return 0.0

    async def _judge_faithfulness(
        self, answer: str, context: str
    ) -> float:
        """Check if the answer only uses information from the context.

        Args:
            answer: The generated answer.
            context: The concatenated context documents.

        Returns:
            A faithfulness score between 0.0 and 1.0.
        """
        if self._judge is None:
            return 0.0

        prompt = (
            f"Context:\n{context[:4000]}\n\n"
            f"Generated answer: {answer}\n\n"
            f"Rate the faithfulness (0.0 to 1.0):"
        )

        try:
            response = await self._judge.call(
                prompt,
                system_prompt=_FAITHFULNESS_SYSTEM_PROMPT,
                temperature=0.0,
            )
            return self._parse_float_score(response.text)
        except Exception:
            logger.warning("Faithfulness judging failed", exc_info=True)
            return 0.0

    @staticmethod
    def _parse_float_score(text: str) -> float:
        """Parse a float score from LLM output, clamped to [0.0, 1.0].

        Args:
            text: Raw LLM response text.

        Returns:
            A float value between 0.0 and 1.0.
        """
        cleaned = text.strip()
        try:
            value = float(cleaned)
        except ValueError:
            # Try to extract the first float-like number from the text
            import re

            match = re.search(r"\d+\.?\d*", cleaned)
            if match:
                value = float(match.group())
            else:
                return 0.0
        return max(0.0, min(1.0, value))

    @staticmethod
    def _aggregate(results: list[_CaseResult]) -> EvalMetrics:
        """Aggregate per-case results into overall metrics.

        Args:
            results: Individual case results to aggregate.

        Returns:
            Aggregated :class:`EvalMetrics`.
        """
        n = len(results)
        if n == 0:
            return EvalMetrics(
                precision_at_k=0.0,
                recall_at_k=0.0,
                mrr=0.0,
                answer_relevance=0.0,
                faithfulness=0.0,
                total_cases=0,
            )

        avg_precision = sum(r.precision for r in results) / n
        avg_recall = sum(r.recall for r in results) / n
        avg_mrr = sum(r.reciprocal_rank for r in results) / n
        avg_relevance = sum(r.relevance for r in results) / n
        avg_faithfulness = sum(r.faithfulness for r in results) / n
        avg_retrieval = sum(r.retrieval_time_ms for r in results) / n
        avg_total = sum(r.total_time_ms for r in results) / n

        # Per-category breakdown
        by_category: dict[str, list[_CaseResult]] = defaultdict(list)
        for r in results:
            by_category[r.category].append(r)

        per_category: dict[str, dict[str, Any]] = {}
        for cat, cat_results in by_category.items():
            cat_n = len(cat_results)
            per_category[cat] = {
                "count": cat_n,
                "precision_at_k": sum(r.precision for r in cat_results) / cat_n,
                "recall_at_k": sum(r.recall for r in cat_results) / cat_n,
                "mrr": sum(r.reciprocal_rank for r in cat_results) / cat_n,
                "answer_relevance": sum(r.relevance for r in cat_results) / cat_n,
                "faithfulness": sum(r.faithfulness for r in cat_results) / cat_n,
            }

        return EvalMetrics(
            precision_at_k=avg_precision,
            recall_at_k=avg_recall,
            mrr=avg_mrr,
            answer_relevance=avg_relevance,
            faithfulness=avg_faithfulness,
            total_cases=n,
            avg_retrieval_time_ms=avg_retrieval,
            avg_total_time_ms=avg_total,
            per_category=per_category,
        )


__all__ = [
    "EvalCase",
    "EvalMetrics",
    "RAGEvaluator",
]
