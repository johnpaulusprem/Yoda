"""
Fallback mechanisms for resilient operations.

Provides fallback chains, model fallback, graceful degradation, and
various fallback strategies.

Example:
    ```python
    from yoda_foundation.resilience.fallback import (
        FallbackChain,
        ModelFallback,
        GracefulDegradation,
        StaticFallback,
        CacheFallback,
        DegradedFallback,
        AlternativeServiceFallback,
    )

    # Create fallback chain with various strategies
    chain = FallbackChain()
    chain.add_fallback("primary", primary_function)
    chain.add_fallback("secondary", secondary_function)
    chain.add_fallback("cache", CacheFallback(cache_client).execute)
    chain.add_fallback("static", StaticFallback({"default": "value"}).execute)

    result = await chain.execute(security_context=context)
    ```
"""

from yoda_foundation.resilience.fallback.default_responses import (
    DefaultResponses,
    FallbackConfig,
    FallbackStrategy,
)
from yoda_foundation.resilience.fallback.fallback_chain import FallbackChain
from yoda_foundation.resilience.fallback.fallback_strategies import (
    AlternativeServiceFallback,
    BaseFallbackStrategy,
    CacheFallback,
    DegradedFallback,
    FallbackExecutionResult,
    FallbackStrategyConfig,
    FallbackStrategyType,
    StaticFallback,
)
from yoda_foundation.resilience.fallback.graceful_degradation import GracefulDegradation
from yoda_foundation.resilience.fallback.model_fallback import ModelFallback


__all__ = [
    "FallbackChain",
    "ModelFallback",
    "GracefulDegradation",
    "DefaultResponses",
    "FallbackConfig",
    "FallbackStrategy",
    # Fallback strategies
    "BaseFallbackStrategy",
    "StaticFallback",
    "CacheFallback",
    "DegradedFallback",
    "AlternativeServiceFallback",
    "FallbackStrategyType",
    "FallbackStrategyConfig",
    "FallbackExecutionResult",
]
