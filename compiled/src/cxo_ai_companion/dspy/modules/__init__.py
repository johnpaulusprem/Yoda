"""DSPy module implementations."""

from __future__ import annotations

from cxo_ai_companion.dspy.modules.chain_of_thought import (
    ChainOfThought,
    ChainOfThoughtConfig,
    ChainOfThoughtResult,
)
from cxo_ai_companion.dspy.modules.predict import (
    BaseDSPyModule,
    Predict,
    PredictConfig,
    PredictResult,
)

__all__ = [
    "Predict",
    "PredictConfig",
    "PredictResult",
    "BaseDSPyModule",
    "ChainOfThought",
    "ChainOfThoughtConfig",
    "ChainOfThoughtResult",
]
