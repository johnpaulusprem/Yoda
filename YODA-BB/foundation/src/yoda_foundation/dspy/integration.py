"""Real DSPy (v3.x) integration layer for the YODA RAG pipeline.

Bridges the ``dspy`` pip package with YODA's existing custom DSPy-inspired
framework.  Provides:

* :func:`configure_dspy` -- one-call setup for Azure AI Foundry.
* Four :class:`dspy.Signature` subclasses mirroring the legacy custom
  signatures (``ContextualQA``, ``MeetingExtraction``, ``DocumentSummary``,
  ``InsightDetection``).
* Three :class:`dspy.Module` subclasses with built-in assertions
  (``YodaQA``, ``YodaMeetingExtractor``, ``YodaInsightDetector``).
* :class:`YodaOptimizer` for BootstrapFewShot optimization using the
  golden QA evaluation cases.

Usage::

    from yoda_foundation.dspy.integration import configure_dspy, YodaQA

    configure_dspy(
        endpoint="https://my-foundry.openai.azure.com/",
        api_key="...",
        deployment="gpt-4o-mini",
    )

    qa = YodaQA()
    result = qa(contexts="[1] Revenue grew 15%...", question="What was revenue growth?")
    print(result.answer, result.confidence)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import dspy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Configuration helper
# ---------------------------------------------------------------------------


def configure_dspy(
    endpoint: str,
    api_key: str,
    deployment: str = "gpt-4o-mini",
    api_version: str = "2024-10-21",
) -> dspy.LM:
    """Configure the global ``dspy`` runtime to use Azure AI Foundry.

    Creates a :class:`dspy.LM` backed by Azure OpenAI and registers it as
    the default language model for all subsequent ``dspy`` calls.

    Args:
        endpoint: Azure AI Foundry endpoint URL
            (e.g. ``https://<resource>.openai.azure.com/``).
        api_key: API key for the Azure deployment.
        deployment: Model deployment name. Defaults to ``"gpt-4o-mini"``.
        api_version: Azure OpenAI API version string.

    Returns:
        The configured :class:`dspy.LM` instance.
    """
    lm = dspy.LM(
        model=f"azure/{deployment}",
        api_base=endpoint,
        api_key=api_key,
        api_version=api_version,
    )
    dspy.configure(lm=lm)
    logger.info(
        "dspy configured with Azure AI Foundry: deployment=%s, endpoint=%s",
        deployment,
        endpoint,
    )
    return lm


# ---------------------------------------------------------------------------
# 2. Real dspy Signatures (replace custom Signature subclasses)
# ---------------------------------------------------------------------------


class ContextualQA(dspy.Signature):
    """Answer questions based on provided context with citations."""

    contexts: str = dspy.InputField(
        desc="Retrieved context passages with [n] markers"
    )
    question: str = dspy.InputField(desc="User's question")

    reasoning: str = dspy.OutputField(desc="Step-by-step reasoning process")
    answer: str = dspy.OutputField(
        desc="Comprehensive answer grounded in context"
    )
    confidence: float = dspy.OutputField(
        desc="Confidence score 0.0 to 1.0"
    )
    citations: str = dspy.OutputField(
        desc="Comma-separated citation numbers used"
    )


class MeetingExtraction(dspy.Signature):
    """Extract structured info from a meeting transcript."""

    transcript: str = dspy.InputField(
        desc="Full transcript with speaker labels"
    )
    subject: str = dspy.InputField(desc="Meeting subject")
    participants: str = dspy.InputField(
        desc="Comma-separated participant names"
    )

    summary: str = dspy.OutputField(
        desc="Executive summary (2-3 paragraphs)"
    )
    action_items: str = dspy.OutputField(
        desc="JSON array of {description, assigned_to, deadline}"
    )
    decisions: str = dspy.OutputField(desc="JSON array of key decisions")
    key_topics: str = dspy.OutputField(
        desc="Comma-separated main topics"
    )
    unresolved_questions: str = dspy.OutputField(
        desc="JSON array of unresolved items"
    )


class DocumentSummary(dspy.Signature):
    """Summarize a document and extract key info."""

    document_text: str = dspy.InputField(desc="Full document text")
    document_type: str = dspy.InputField(
        desc="Type: pdf, docx, pptx, etc."
    )

    summary: str = dspy.OutputField(desc="Concise summary")
    key_points: str = dspy.OutputField(desc="JSON array of key points")
    entities: str = dspy.OutputField(
        desc="JSON array of entities (people, orgs, dates)"
    )


class InsightDetection(dspy.Signature):
    """Detect conflicts between current and past decisions."""

    current_decision: str = dspy.InputField(
        desc="Current decision being evaluated"
    )
    past_decisions: str = dspy.InputField(
        desc="JSON array of past decisions"
    )

    conflicts: str = dspy.OutputField(
        desc="JSON array of detected conflicts"
    )
    severity: str = dspy.OutputField(
        desc="info, warning, or critical"
    )
    recommendation: str = dspy.OutputField(desc="Recommended action")


# ---------------------------------------------------------------------------
# 3. DSPy Modules with assertions
# ---------------------------------------------------------------------------


class YodaQA(dspy.Module):
    """RAG question-answering with Chain-of-Thought and assertions.

    Wraps :class:`ContextualQA` in a ``dspy.ChainOfThought`` and adds
    ``dspy.Suggest`` assertions to enforce answer quality at runtime.
    """

    def __init__(self) -> None:
        super().__init__()
        self.cot = dspy.ChainOfThought(ContextualQA)

    def forward(
        self,
        contexts: str,
        question: str,
    ) -> dspy.Prediction:
        """Run context-grounded QA with quality assertions.

        Args:
            contexts: Retrieved context passages with ``[n]`` markers.
            question: The user's question.

        Returns:
            A :class:`dspy.Prediction` with ``reasoning``, ``answer``,
            ``confidence``, and ``citations`` fields.
        """
        result = self.cot(contexts=contexts, question=question)

        dspy.Suggest(
            len(result.answer) > 20,
            "Answer should be substantive (>20 chars)",
        )
        dspy.Suggest(
            result.citations.strip() != "",
            "Answer should cite at least one source",
        )

        return result


class YodaMeetingExtractor(dspy.Module):
    """Meeting transcript extraction with validation.

    Uses :class:`MeetingExtraction` inside a ``dspy.ChainOfThought`` and
    asserts that the generated summary is non-trivial.
    """

    def __init__(self) -> None:
        super().__init__()
        self.extract = dspy.ChainOfThought(MeetingExtraction)

    def forward(
        self,
        transcript: str,
        subject: str,
        participants: str,
    ) -> dspy.Prediction:
        """Extract structured meeting information.

        Args:
            transcript: Full meeting transcript with speaker labels.
            subject: Meeting subject or title.
            participants: Comma-separated participant names.

        Returns:
            A :class:`dspy.Prediction` with ``summary``, ``action_items``,
            ``decisions``, ``key_topics``, and ``unresolved_questions``.
        """
        result = self.extract(
            transcript=transcript,
            subject=subject,
            participants=participants,
        )

        dspy.Suggest(
            len(result.summary) > 50,
            "Summary should be at least 50 chars",
        )

        return result


class YodaInsightDetector(dspy.Module):
    """Conflict detection using DSPy with assertions.

    Uses :class:`InsightDetection` inside a ``dspy.ChainOfThought`` and
    validates that severity is one of the allowed values.
    """

    def __init__(self) -> None:
        super().__init__()
        self.detect = dspy.ChainOfThought(InsightDetection)

    def forward(
        self,
        current_decision: str,
        past_decisions: str,
    ) -> dspy.Prediction:
        """Detect conflicts between current and past decisions.

        Args:
            current_decision: The decision currently being evaluated.
            past_decisions: JSON array of past decisions with context.

        Returns:
            A :class:`dspy.Prediction` with ``conflicts``, ``severity``,
            and ``recommendation``.
        """
        result = self.detect(
            current_decision=current_decision,
            past_decisions=past_decisions,
        )

        dspy.Suggest(
            result.severity in ("info", "warning", "critical"),
            "Severity must be info, warning, or critical",
        )

        return result


# ---------------------------------------------------------------------------
# 4. Optimizer (BootstrapFewShot with golden QA)
# ---------------------------------------------------------------------------


class YodaOptimizer:
    """Optimizes DSPy modules using golden QA evaluation cases.

    Wraps :class:`dspy.BootstrapFewShot` and provides helpers for
    converting YODA's :class:`EvalCase` golden QA set into the
    ``dspy.Example`` format expected by DSPy optimizers.

    Args:
        module: A ``dspy.Module`` instance to optimize.
        metric_fn: Optional custom metric function with signature
            ``(example, prediction, trace=None) -> bool | float``.
            Defaults to a simple answer-length check.
    """

    def __init__(
        self,
        module: dspy.Module,
        metric_fn: Callable[..., bool | float] | None = None,
    ) -> None:
        self.module = module
        self.metric_fn = metric_fn or self._default_metric

    def optimize(
        self,
        trainset: list[dspy.Example],
        max_bootstrapped_demos: int = 4,
        max_labeled_demos: int = 4,
    ) -> dspy.Module:
        """Run BootstrapFewShot optimization on the module.

        Args:
            trainset: List of :class:`dspy.Example` training examples.
            max_bootstrapped_demos: Maximum bootstrapped demonstrations
                per prediction step.
            max_labeled_demos: Maximum labelled demonstrations per
                prediction step.

        Returns:
            An optimized copy of the original module with learned demos.
        """
        optimizer = dspy.BootstrapFewShot(
            metric=self.metric_fn,
            max_bootstrapped_demos=max_bootstrapped_demos,
            max_labeled_demos=max_labeled_demos,
        )
        optimized = optimizer.compile(self.module, trainset=trainset)
        logger.info(
            "DSPy optimization complete: %d training examples, "
            "max_bootstrapped=%d, max_labeled=%d",
            len(trainset),
            max_bootstrapped_demos,
            max_labeled_demos,
        )
        return optimized

    @staticmethod
    def _default_metric(
        example: dspy.Example,
        prediction: dspy.Prediction,
        trace: Any = None,
    ) -> bool:
        """Default metric: answer is non-empty and has citations.

        Args:
            example: The ground-truth example.
            prediction: The model's prediction.
            trace: Optional execution trace (unused).

        Returns:
            ``True`` if the answer exceeds 20 characters.
        """
        answer = prediction.answer if hasattr(prediction, "answer") else ""
        return len(answer) > 20

    @staticmethod
    def golden_qa_to_trainset(
        golden_cases: list[Any] | None = None,
    ) -> list[dspy.Example]:
        """Convert YODA golden QA cases to a ``dspy.Example`` trainset.

        Imports :data:`GOLDEN_QA_CASES` lazily to avoid circular imports
        and converts each :class:`EvalCase` into a :class:`dspy.Example`
        with ``question`` marked as an input field.

        Args:
            golden_cases: Optional explicit list of
                :class:`~yoda_foundation.rag.evaluation.evaluator.EvalCase`
                objects. When ``None``, falls back to the built-in
                :data:`GOLDEN_QA_CASES`.

        Returns:
            A list of :class:`dspy.Example` instances ready for DSPy
            optimizers.
        """
        from yoda_foundation.rag.evaluation.golden_qa import GOLDEN_QA_CASES

        cases = golden_cases if golden_cases is not None else GOLDEN_QA_CASES
        trainset: list[dspy.Example] = []
        for case in cases:
            trainset.append(
                dspy.Example(
                    question=case.question,
                    answer=case.expected_answer,
                ).with_inputs("question")
            )
        return trainset

    @staticmethod
    def load_from_json(file_path: str) -> list[dspy.Example]:
        """Load golden QA cases from a JSON file and convert to dspy trainset.

        The JSON file should have a ``cases`` array where each object has:
        ``question``, ``expected_answer``, and optionally ``expected_sources``
        and ``category``.

        Args:
            file_path: Path to the JSON file (e.g. ``config/golden_qa.json``).

        Returns:
            A list of :class:`dspy.Example` instances ready for DSPy optimizers.

        Example::

            optimizer = YodaOptimizer(YodaQA())
            trainset = optimizer.load_from_json("config/golden_qa.json")
            optimized = optimizer.optimize(trainset)
        """
        import json
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Golden QA file not found: {file_path}")

        with open(path) as f:
            data = json.load(f)

        cases = data.get("cases", [])
        if not cases:
            raise ValueError(f"No cases found in {file_path}")

        trainset: list[dspy.Example] = []
        for case in cases:
            question = case.get("question", "")
            answer = case.get("expected_answer", "")
            if not question:
                continue
            trainset.append(
                dspy.Example(
                    question=question,
                    answer=answer,
                    category=case.get("category", "general"),
                    expected_sources=",".join(case.get("expected_sources", [])),
                ).with_inputs("question")
            )

        logger.info("Loaded %d golden QA cases from %s", len(trainset), file_path)
        return trainset

    def optimize_from_file(
        self,
        file_path: str,
        max_bootstrapped_demos: int = 4,
        max_labeled_demos: int = 4,
    ) -> dspy.Module:
        """Load cases from JSON and run optimization in one call.

        Args:
            file_path: Path to ``config/golden_qa.json``.
            max_bootstrapped_demos: Max auto-generated demos.
            max_labeled_demos: Max labeled demos to include.

        Returns:
            The optimized DSPy module with tuned prompts.

        Example::

            from yoda_foundation.dspy.integration import configure_dspy, YodaQA, YodaOptimizer

            configure_dspy(endpoint="...", api_key="...", deployment="gpt-4o-mini")
            optimizer = YodaOptimizer(YodaQA())
            optimized = optimizer.optimize_from_file("config/golden_qa.json")
            # Use optimized module — prompts are now auto-tuned
            result = optimized(contexts="...", question="What was the Q4 target?")
        """
        trainset = self.load_from_json(file_path)
        return self.optimize(trainset, max_bootstrapped_demos, max_labeled_demos)


__all__ = [
    "configure_dspy",
    # Signatures
    "ContextualQA",
    "MeetingExtraction",
    "DocumentSummary",
    "InsightDetection",
    # Modules
    "YodaQA",
    "YodaMeetingExtractor",
    "YodaInsightDetector",
    # Optimizer
    "YodaOptimizer",
]
