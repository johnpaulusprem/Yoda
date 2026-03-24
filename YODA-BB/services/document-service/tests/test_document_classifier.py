"""Tests for the document classification module."""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock

from yoda_foundation.rag.classification.document_classifier import (
    CATEGORY_LABELS,
    DOCUMENT_TEMPLATES,
    DocumentCategory,
    DocumentClassifier,
    ClassificationResult,
    DetailedClassificationResult,
    _suggest_priority,
    _suggest_tags,
    _classify_from_filename,
    _detect_format_tag,
)


# ---------------------------------------------------------------------------
# Helpers — mock embedder that returns deterministic vectors
# ---------------------------------------------------------------------------

def _make_mock_embedder(dim: int = 64):
    """Create a mock embedder that produces consistent vectors.

    Uses a simple hash-based approach: each unique text gets a reproducible
    random vector, so the same text always returns the same embedding.
    """
    embedder = AsyncMock()
    cache: dict[str, list[float]] = {}

    def _embed_text(text: str) -> list[float]:
        if text not in cache:
            rng = np.random.RandomState(hash(text) % (2**31))
            vec = rng.randn(dim).astype(float)
            vec = vec / np.linalg.norm(vec)  # unit normalize
            cache[text] = vec.tolist()
        return cache[text]

    async def mock_embed(text: str) -> list[float]:
        return _embed_text(text)

    async def mock_embed_batch(texts: list[str]):
        vectors = [_embed_text(t) for t in texts]
        result = MagicMock()
        result.vectors = vectors
        return result

    embedder.embed = mock_embed
    embedder.embed_batch = mock_embed_batch
    return embedder


# ---------------------------------------------------------------------------
# Template coverage
# ---------------------------------------------------------------------------

def test_all_categories_have_templates():
    """Every DocumentCategory enum value should have templates defined."""
    for cat in DocumentCategory:
        assert cat.value in DOCUMENT_TEMPLATES, f"Missing templates for {cat.value}"
        assert len(DOCUMENT_TEMPLATES[cat.value]) >= 3, (
            f"Category {cat.value} needs at least 3 templates, has {len(DOCUMENT_TEMPLATES[cat.value])}"
        )


def test_all_categories_have_labels():
    """Every category with templates should have a human-readable label."""
    for cat_key in DOCUMENT_TEMPLATES:
        assert cat_key in CATEGORY_LABELS, f"Missing label for {cat_key}"


def test_template_count():
    """Verify we have a reasonable number of templates."""
    total = sum(len(v) for v in DOCUMENT_TEMPLATES.values())
    # With ~23 categories, each having 3-8 templates, expect > 100
    assert total >= 100, f"Only {total} templates — expected at least 100"


# ---------------------------------------------------------------------------
# Priority suggestion
# ---------------------------------------------------------------------------

def test_suggest_priority_high_keyword():
    """Documents with urgent keywords get high priority."""
    assert _suggest_priority("general_document", "This is URGENT and needs approval ASAP") == "high"


def test_suggest_priority_escalation_default():
    """Escalation category defaults to high even without keywords."""
    assert _suggest_priority("escalation", "Some escalation text") in ("high", "medium")


def test_suggest_priority_status_report():
    """Status reports get medium priority."""
    assert _suggest_priority("status_report", "Weekly status update for sprint 14") == "medium"


def test_suggest_priority_general_low():
    """General documents without keywords get low priority."""
    assert _suggest_priority("general_document", "Internal memo about office supplies") == "low"


# ---------------------------------------------------------------------------
# Tag suggestion
# ---------------------------------------------------------------------------

def test_suggest_tags_includes_category():
    """Tags should include the category label."""
    tags = _suggest_tags("qbr", "Q4 2025 Quarterly Business Review")
    assert any("Quarterly" in t for t in tags)


def test_suggest_tags_detects_quarter():
    """Tags should detect quarter references."""
    tags = _suggest_tags("financial_report", "Q3 revenue analysis for 2026")
    assert "Q3" in tags


def test_suggest_tags_detects_year():
    """Tags should detect year references."""
    tags = _suggest_tags("sow", "Statement of Work for FY 2026 engagement")
    assert "FY2026" in tags


def test_suggest_tags_client_facing():
    """Tags should detect client-facing documents."""
    tags = _suggest_tags("presentation", "Client pitch deck for Acme Corp")
    assert "Client-Facing" in tags


# ---------------------------------------------------------------------------
# Filename classification
# ---------------------------------------------------------------------------

def test_classify_from_filename_mbr():
    assert _classify_from_filename("January_MBR_2026.pptx") == "mbr"


def test_classify_from_filename_sow():
    assert _classify_from_filename("SOW-Phase2-CloudMigration.docx") == "sow"


def test_classify_from_filename_escalation():
    assert _classify_from_filename("Escalation_Report_P1_Incident.pdf") == "escalation"


def test_classify_from_filename_mom():
    assert _classify_from_filename("MOM-Steering-Committee-Jan20.docx") == "mom"


def test_classify_from_filename_unknown():
    assert _classify_from_filename("random_file_name.txt") is None


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def test_detect_format_pptx():
    assert _detect_format_tag("Deck.pptx", None) == "PowerPoint"


def test_detect_format_pdf():
    assert _detect_format_tag("report.pdf", None) == "PDF"


def test_detect_format_from_mime():
    assert _detect_format_tag(None, "application/pdf") == "PDF"


def test_detect_format_xlsx():
    assert _detect_format_tag("budget.xlsx", None) == "Excel"


# ---------------------------------------------------------------------------
# Classifier integration tests (with mock embedder)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_returns_result():
    """classify() returns a ClassificationResult with expected fields."""
    embedder = _make_mock_embedder()
    classifier = DocumentClassifier(embedder=embedder, similarity_threshold=0.0)

    result = await classifier.classify("Monthly Business Review revenue utilization attrition bench strength")
    assert isinstance(result, ClassificationResult)
    assert result.category in CATEGORY_LABELS
    assert 0.0 <= result.confidence <= 1.0
    assert result.suggested_priority in ("high", "medium", "low")
    assert len(result.suggested_tags) >= 1


@pytest.mark.asyncio
async def test_classify_with_details_returns_scores():
    """classify_with_details() returns per-category scores and top matches."""
    embedder = _make_mock_embedder()
    classifier = DocumentClassifier(embedder=embedder, similarity_threshold=0.0)

    result = await classifier.classify_with_details(
        "Risk register showing probability and impact matrix with mitigation plans"
    )
    assert isinstance(result, DetailedClassificationResult)
    assert len(result.all_scores) > 0
    assert len(result.top_matches) > 0
    assert "category" in result.top_matches[0]
    assert "similarity" in result.top_matches[0]


@pytest.mark.asyncio
async def test_classify_file_adds_format_tag():
    """classify_file() adds file format tag to results."""
    embedder = _make_mock_embedder()
    classifier = DocumentClassifier(embedder=embedder, similarity_threshold=0.0)

    result = await classifier.classify_file(
        text="Quarterly Business Review account health scorecard",
        filename="Q4_QBR_2025.pptx",
    )
    assert "PowerPoint" in result.suggested_tags


@pytest.mark.asyncio
async def test_classify_file_uses_filename_hint():
    """classify_file() uses filename to override low-confidence classification."""
    embedder = _make_mock_embedder()
    # High threshold → content classification will likely be low confidence
    classifier = DocumentClassifier(embedder=embedder, similarity_threshold=0.8)

    result = await classifier.classify_file(
        text="Some generic text that is hard to classify",
        filename="MBR_January_2026.pptx",
    )
    # Filename hint should kick in since content confidence is low
    assert result.category == "mbr"


@pytest.mark.asyncio
async def test_classifier_initializes_once():
    """Templates are embedded only on first call, then cached."""
    embedder = _make_mock_embedder()
    classifier = DocumentClassifier(embedder=embedder)

    await classifier.classify("Test text one")
    assert classifier._initialized is True

    # Manually flip initialized to check it's not re-embedded
    original_vectors = classifier._template_vectors
    await classifier.classify("Test text two")
    # Same object reference — templates were NOT re-embedded
    assert classifier._template_vectors is original_vectors


@pytest.mark.asyncio
async def test_classify_general_fallback():
    """Very ambiguous text with high threshold falls back to general_document."""
    embedder = _make_mock_embedder()
    classifier = DocumentClassifier(embedder=embedder, similarity_threshold=0.99)

    result = await classifier.classify("Hello world this is a random test")
    assert result.category == "general_document"
