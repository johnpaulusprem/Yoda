"""DSPy abstraction layer for the CXO AI Companion.

Provides typed signatures, structured LLM calls, and composable modules
inspired by the DSPy framework.  This is a custom implementation that
does NOT depend on the ``dspy`` pip package.
"""

from __future__ import annotations

from cxo_ai_companion.dspy.adapters.llm_adapter import (
    CachedLLMAdapter,
    LLMAdapter,
)
from cxo_ai_companion.dspy.modules.chain_of_thought import ChainOfThought
from cxo_ai_companion.dspy.modules.predict import Predict
from cxo_ai_companion.dspy.signatures.base_signature import (
    InputField,
    OutputField,
    Signature,
)
from cxo_ai_companion.dspy.signatures.rag_signatures import (
    ContextualQA,
    DocumentSummary,
    InsightDetection,
    MeetingExtraction,
)

__all__ = [
    # Core signature system
    "Signature",
    "InputField",
    "OutputField",
    # Modules
    "Predict",
    "ChainOfThought",
    # Adapters
    "LLMAdapter",
    "CachedLLMAdapter",
    # CXO-specific signatures
    "ContextualQA",
    "MeetingExtraction",
    "DocumentSummary",
    "InsightDetection",
]
