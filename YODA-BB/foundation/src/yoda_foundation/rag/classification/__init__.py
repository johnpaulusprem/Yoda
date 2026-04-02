"""Document classification using vector-based template matching.

Classifies documents into enterprise categories (MBR, QBR, SOW, MSA,
status reports, risk documents, MOMs, escalations, etc.) by comparing
embeddings against pre-defined templates via cosine similarity.
"""

from __future__ import annotations

from yoda_foundation.rag.classification.document_classifier import (
    CATEGORY_LABELS,
    DOCUMENT_TEMPLATES,
    ClassificationResult,
    DetailedClassificationResult,
    DocumentCategory,
    DocumentClassifier,
)

__all__ = [
    "CATEGORY_LABELS",
    "DOCUMENT_TEMPLATES",
    "ClassificationResult",
    "DetailedClassificationResult",
    "DocumentCategory",
    "DocumentClassifier",
]
