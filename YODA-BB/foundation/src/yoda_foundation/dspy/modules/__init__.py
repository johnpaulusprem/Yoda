"""DSPy module implementations."""

from __future__ import annotations

from yoda_foundation.dspy.modules.chain_of_thought import (
    ChainOfThought,
    ChainOfThoughtConfig,
    ChainOfThoughtResult,
)
from yoda_foundation.dspy.modules.predict import (
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
