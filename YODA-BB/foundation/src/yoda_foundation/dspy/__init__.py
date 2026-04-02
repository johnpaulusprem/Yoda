"""DSPy abstraction layer for the YODA AI Companion.

Provides TWO parallel APIs:

1. **Real DSPy integration** (recommended) -- backed by the ``dspy`` pip
   package (v3.x).  Signatures, modules, and optimizer that plug directly
   into the DSPy ecosystem.

2. **Legacy custom modules** (backward-compatible) -- the original
   hand-written ``Signature``/``Predict``/``ChainOfThought`` classes that
   predate the real DSPy integration.  Existing call-sites that import from
   ``yoda_foundation.dspy`` will continue to work without changes.

Usage (new real DSPy path)::

    from yoda_foundation.dspy.integration import configure_dspy, YodaQA
    configure_dspy(endpoint="...", api_key="...")
    result = YodaQA()(contexts="...", question="...")

Usage (legacy path, still works)::

    from yoda_foundation.dspy import ChainOfThought, ContextualQA
"""

from __future__ import annotations

# ── Real DSPy integration (recommended) ────────────────────────────────────
from yoda_foundation.dspy.integration import (
    ContextualQA as DspyContextualQA,
    DocumentSummary as DspyDocumentSummary,
    InsightDetection as DspyInsightDetection,
    MeetingExtraction as DspyMeetingExtraction,
    YodaInsightDetector,
    YodaMeetingExtractor,
    YodaOptimizer,
    YodaQA,
    configure_dspy,
)

# ── Legacy custom modules (backward compatible) ───────────────────────────
from yoda_foundation.dspy.adapters.llm_adapter import (
    CachedLLMAdapter,
    LLMAdapter,
)
from yoda_foundation.dspy.modules.chain_of_thought import ChainOfThought
from yoda_foundation.dspy.modules.predict import Predict
from yoda_foundation.dspy.signatures.base_signature import (
    InputField,
    OutputField,
    Signature,
)
from yoda_foundation.dspy.signatures.rag_signatures import (
    ContextualQA,
    DocumentSummary,
    InsightDetection,
    MeetingExtraction,
)

__all__ = [
    # ── Real DSPy integration ──────────────────────────────────────────
    "configure_dspy",
    "DspyContextualQA",
    "DspyMeetingExtraction",
    "DspyDocumentSummary",
    "DspyInsightDetection",
    "YodaQA",
    "YodaMeetingExtractor",
    "YodaInsightDetector",
    "YodaOptimizer",
    # ── Legacy custom framework ────────────────────────────────────────
    "Signature",
    "InputField",
    "OutputField",
    "Predict",
    "ChainOfThought",
    "LLMAdapter",
    "CachedLLMAdapter",
    "ContextualQA",
    "MeetingExtraction",
    "DocumentSummary",
    "InsightDetection",
]
