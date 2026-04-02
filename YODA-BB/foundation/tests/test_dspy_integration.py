"""Tests for the real DSPy (v3.x) integration layer.

Validates that:
1. ``configure_dspy`` creates an LM instance.
2. Signatures have correct input/output fields.
3. Modules can be instantiated without error.
4. ``YodaOptimizer`` converts golden QA cases to a trainset.
5. Backward compatibility: legacy custom modules still import correctly.
6. ``RAGPipeline`` accepts the ``dspy_native_module`` parameter.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import dspy
import pytest


# ── 1. configure_dspy ──────────────────────────────────────────────────────


class TestConfigureDspy:
    """Tests for :func:`configure_dspy`."""

    def test_configure_dspy_returns_lm_instance(self) -> None:
        """configure_dspy should return a dspy.LM and register it globally."""
        from yoda_foundation.dspy.integration import configure_dspy

        lm = configure_dspy(
            endpoint="https://fake-endpoint.openai.azure.com/",
            api_key="fake-key-for-testing",
            deployment="gpt-4o-mini",
        )
        assert isinstance(lm, dspy.LM)

    def test_configure_dspy_custom_deployment(self) -> None:
        """configure_dspy should accept a custom deployment name."""
        from yoda_foundation.dspy.integration import configure_dspy

        lm = configure_dspy(
            endpoint="https://fake-endpoint.openai.azure.com/",
            api_key="fake-key",
            deployment="gpt-4o",
            api_version="2024-10-21",
        )
        assert isinstance(lm, dspy.LM)
        assert "gpt-4o" in lm.model


# ── 2. Signature field validation ──────────────────────────────────────────


class TestSignatures:
    """Tests for the four real dspy Signature classes."""

    def test_contextual_qa_input_fields(self) -> None:
        """ContextualQA should declare 'contexts' and 'question' as inputs."""
        from yoda_foundation.dspy.integration import ContextualQA

        schema = ContextualQA.model_json_schema()
        properties = schema.get("properties", {})
        assert "contexts" in properties
        assert "question" in properties

    def test_contextual_qa_output_fields(self) -> None:
        """ContextualQA should declare reasoning, answer, confidence, citations."""
        from yoda_foundation.dspy.integration import ContextualQA

        schema = ContextualQA.model_json_schema()
        properties = schema.get("properties", {})
        for field_name in ("reasoning", "answer", "confidence", "citations"):
            assert field_name in properties, f"Missing output field: {field_name}"

    def test_meeting_extraction_fields(self) -> None:
        """MeetingExtraction should have transcript/subject/participants inputs."""
        from yoda_foundation.dspy.integration import MeetingExtraction

        schema = MeetingExtraction.model_json_schema()
        properties = schema.get("properties", {})
        for field_name in ("transcript", "subject", "participants"):
            assert field_name in properties
        for field_name in (
            "summary", "action_items", "decisions",
            "key_topics", "unresolved_questions",
        ):
            assert field_name in properties

    def test_document_summary_fields(self) -> None:
        """DocumentSummary should have document_text/document_type inputs."""
        from yoda_foundation.dspy.integration import DocumentSummary

        schema = DocumentSummary.model_json_schema()
        properties = schema.get("properties", {})
        assert "document_text" in properties
        assert "document_type" in properties
        assert "summary" in properties
        assert "key_points" in properties
        assert "entities" in properties

    def test_insight_detection_fields(self) -> None:
        """InsightDetection should have current_decision/past_decisions inputs."""
        from yoda_foundation.dspy.integration import InsightDetection

        schema = InsightDetection.model_json_schema()
        properties = schema.get("properties", {})
        assert "current_decision" in properties
        assert "past_decisions" in properties
        assert "conflicts" in properties
        assert "severity" in properties
        assert "recommendation" in properties

    def test_signatures_are_dspy_signature_subclasses(self) -> None:
        """All four signatures should subclass dspy.Signature."""
        from yoda_foundation.dspy.integration import (
            ContextualQA,
            DocumentSummary,
            InsightDetection,
            MeetingExtraction,
        )

        for sig_cls in (ContextualQA, MeetingExtraction, DocumentSummary, InsightDetection):
            assert issubclass(sig_cls, dspy.Signature), (
                f"{sig_cls.__name__} is not a dspy.Signature subclass"
            )


# ── 3. Module instantiation ───────────────────────────────────────────────


class TestModules:
    """Tests for the three YODA dspy.Module subclasses."""

    def test_yoda_qa_instantiation(self) -> None:
        """YodaQA should instantiate without errors."""
        from yoda_foundation.dspy.integration import YodaQA

        module = YodaQA()
        assert isinstance(module, dspy.Module)
        assert hasattr(module, "cot")

    def test_yoda_meeting_extractor_instantiation(self) -> None:
        """YodaMeetingExtractor should instantiate without errors."""
        from yoda_foundation.dspy.integration import YodaMeetingExtractor

        module = YodaMeetingExtractor()
        assert isinstance(module, dspy.Module)
        assert hasattr(module, "extract")

    def test_yoda_insight_detector_instantiation(self) -> None:
        """YodaInsightDetector should instantiate without errors."""
        from yoda_foundation.dspy.integration import YodaInsightDetector

        module = YodaInsightDetector()
        assert isinstance(module, dspy.Module)
        assert hasattr(module, "detect")


# ── 4. YodaOptimizer golden QA conversion ─────────────────────────────────


class TestYodaOptimizer:
    """Tests for :class:`YodaOptimizer`."""

    def test_golden_qa_to_trainset_returns_examples(self) -> None:
        """golden_qa_to_trainset should produce dspy.Example instances."""
        from yoda_foundation.dspy.integration import YodaOptimizer

        trainset = YodaOptimizer.golden_qa_to_trainset()
        assert len(trainset) > 0
        assert all(isinstance(ex, dspy.Example) for ex in trainset)

    def test_golden_qa_to_trainset_has_correct_count(self) -> None:
        """The trainset should contain the same number of cases as GOLDEN_QA_CASES."""
        from yoda_foundation.dspy.integration import YodaOptimizer
        from yoda_foundation.rag.evaluation.golden_qa import GOLDEN_QA_CASES

        trainset = YodaOptimizer.golden_qa_to_trainset()
        assert len(trainset) == len(GOLDEN_QA_CASES)

    def test_golden_qa_trainset_has_question_and_answer(self) -> None:
        """Each example should have 'question' and 'answer' fields."""
        from yoda_foundation.dspy.integration import YodaOptimizer

        trainset = YodaOptimizer.golden_qa_to_trainset()
        for example in trainset:
            assert hasattr(example, "question")
            assert hasattr(example, "answer")
            assert len(example.question) > 0
            assert len(example.answer) > 0

    def test_golden_qa_trainset_question_is_input(self) -> None:
        """'question' should be marked as an input field via with_inputs."""
        from yoda_foundation.dspy.integration import YodaOptimizer

        trainset = YodaOptimizer.golden_qa_to_trainset()
        for example in trainset:
            # dspy.Example stores input keys in ._input_keys
            input_keys = example.inputs().keys()
            assert "question" in input_keys

    def test_golden_qa_to_trainset_with_explicit_cases(self) -> None:
        """golden_qa_to_trainset should accept explicit cases."""
        from yoda_foundation.dspy.integration import YodaOptimizer
        from yoda_foundation.rag.evaluation.evaluator import EvalCase

        custom_cases = [
            EvalCase(
                question="What is X?",
                expected_answer="X is Y.",
                expected_sources=["doc1"],
                category="test",
            ),
        ]
        trainset = YodaOptimizer.golden_qa_to_trainset(golden_cases=custom_cases)
        assert len(trainset) == 1
        assert trainset[0].question == "What is X?"
        assert trainset[0].answer == "X is Y."

    def test_optimizer_instantiation(self) -> None:
        """YodaOptimizer should instantiate with a dspy.Module."""
        from yoda_foundation.dspy.integration import YodaOptimizer, YodaQA

        module = YodaQA()
        optimizer = YodaOptimizer(module=module)
        assert optimizer.module is module
        assert optimizer.metric_fn is not None

    def test_default_metric_accepts_prediction(self) -> None:
        """The default metric should return True for long answers."""
        from yoda_foundation.dspy.integration import YodaOptimizer

        example = dspy.Example(question="test", answer="expected answer")
        prediction = dspy.Prediction(
            answer="This is a sufficiently long answer that exceeds twenty characters."
        )
        result = YodaOptimizer._default_metric(example, prediction)
        assert result is True

    def test_default_metric_rejects_short_answer(self) -> None:
        """The default metric should return False for short answers."""
        from yoda_foundation.dspy.integration import YodaOptimizer

        example = dspy.Example(question="test", answer="expected")
        prediction = dspy.Prediction(answer="Short.")
        result = YodaOptimizer._default_metric(example, prediction)
        assert result is False


# ── 5. Backward compatibility ──────────────────────────────────────────────


class TestBackwardCompatibility:
    """Verify that the legacy custom DSPy modules still import correctly."""

    def test_legacy_signature_import(self) -> None:
        """Signature, InputField, OutputField should import from yoda_foundation.dspy."""
        from yoda_foundation.dspy import InputField, OutputField, Signature

        assert Signature is not None
        assert InputField is not None
        assert OutputField is not None

    def test_legacy_predict_import(self) -> None:
        """Predict should still be importable from yoda_foundation.dspy."""
        from yoda_foundation.dspy import Predict

        assert Predict is not None

    def test_legacy_chain_of_thought_import(self) -> None:
        """ChainOfThought should still be importable from yoda_foundation.dspy."""
        from yoda_foundation.dspy import ChainOfThought

        assert ChainOfThought is not None

    def test_legacy_adapter_import(self) -> None:
        """LLMAdapter, CachedLLMAdapter should import from yoda_foundation.dspy."""
        from yoda_foundation.dspy import CachedLLMAdapter, LLMAdapter

        assert LLMAdapter is not None
        assert CachedLLMAdapter is not None

    def test_legacy_rag_signatures_import(self) -> None:
        """All four custom signatures should still be importable."""
        from yoda_foundation.dspy import (
            ContextualQA,
            DocumentSummary,
            InsightDetection,
            MeetingExtraction,
        )

        assert ContextualQA is not None
        assert MeetingExtraction is not None
        assert DocumentSummary is not None
        assert InsightDetection is not None

    def test_legacy_and_dspy_signatures_are_distinct(self) -> None:
        """The legacy ContextualQA and DspyContextualQA should be different classes."""
        from yoda_foundation.dspy import ContextualQA, DspyContextualQA

        assert ContextualQA is not DspyContextualQA

    def test_dspy_init_exports_new_symbols(self) -> None:
        """The dspy __init__ should export all new real-DSPy symbols."""
        from yoda_foundation.dspy import (
            DspyContextualQA,
            YodaInsightDetector,
            YodaMeetingExtractor,
            YodaOptimizer,
            YodaQA,
            configure_dspy,
        )

        assert configure_dspy is not None
        assert DspyContextualQA is not None
        assert YodaQA is not None
        assert YodaMeetingExtractor is not None
        assert YodaInsightDetector is not None
        assert YodaOptimizer is not None


# ── 6. RAGPipeline dual-mode support ──────────────────────────────────────


class TestRAGPipelineDualMode:
    """Tests for RAGPipeline with the new dspy_native_module parameter."""

    def test_pipeline_rejects_no_module(self) -> None:
        """RAGPipeline should raise ValueError when no module is provided."""
        from yoda_foundation.rag.pipeline.rag_pipeline import RAGPipeline

        with pytest.raises(ValueError, match="Neither was provided"):
            RAGPipeline(
                retriever=MagicMock(),
                context_builder=MagicMock(),
                citation_tracker=MagicMock(),
                dspy_module=None,
                dspy_native_module=None,
            )

    def test_pipeline_accepts_native_module(self) -> None:
        """RAGPipeline should accept a dspy_native_module without dspy_module."""
        from yoda_foundation.dspy.integration import YodaQA
        from yoda_foundation.rag.pipeline.rag_pipeline import RAGPipeline

        pipeline = RAGPipeline(
            retriever=MagicMock(),
            context_builder=MagicMock(),
            citation_tracker=MagicMock(),
            dspy_native_module=YodaQA(),
        )
        assert pipeline._use_real_dspy is True
        assert pipeline._dspy_native_module is not None

    def test_pipeline_accepts_legacy_module(self) -> None:
        """RAGPipeline should accept legacy dspy_module without native module."""
        from yoda_foundation.rag.pipeline.rag_pipeline import RAGPipeline

        mock_cot = MagicMock()
        pipeline = RAGPipeline(
            retriever=MagicMock(),
            context_builder=MagicMock(),
            citation_tracker=MagicMock(),
            dspy_module=mock_cot,
        )
        assert pipeline._use_real_dspy is False
        assert pipeline._dspy_module is mock_cot

    def test_pipeline_prefers_native_when_both_provided(self) -> None:
        """When both modules are provided, real DSPy should take priority."""
        from yoda_foundation.dspy.integration import YodaQA
        from yoda_foundation.rag.pipeline.rag_pipeline import RAGPipeline

        pipeline = RAGPipeline(
            retriever=MagicMock(),
            context_builder=MagicMock(),
            citation_tracker=MagicMock(),
            dspy_module=MagicMock(),
            dspy_native_module=YodaQA(),
        )
        assert pipeline._use_real_dspy is True


# ── 7. Integration module __all__ exports ─────────────────────────────────


class TestIntegrationExports:
    """Verify that integration.py exports the expected public API."""

    def test_integration_all_exports(self) -> None:
        """The integration module __all__ should list all public symbols."""
        from yoda_foundation.dspy import integration

        expected = {
            "configure_dspy",
            "ContextualQA",
            "MeetingExtraction",
            "DocumentSummary",
            "InsightDetection",
            "YodaQA",
            "YodaMeetingExtractor",
            "YodaInsightDetector",
            "YodaOptimizer",
        }
        assert set(integration.__all__) == expected
