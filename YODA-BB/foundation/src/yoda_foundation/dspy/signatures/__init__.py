"""DSPy signature definitions."""

from __future__ import annotations

from yoda_foundation.dspy.signatures.base_signature import (
    InputField,
    OutputField,
    Signature,
    SignatureField,
)
from yoda_foundation.dspy.signatures.rag_signatures import (
    ContextualQA,
    DocumentSummary,
    InsightDetection,
    MeetingExtraction,
)

__all__ = [
    "Signature",
    "InputField",
    "OutputField",
    "SignatureField",
    "ContextualQA",
    "MeetingExtraction",
    "DocumentSummary",
    "InsightDetection",
]
