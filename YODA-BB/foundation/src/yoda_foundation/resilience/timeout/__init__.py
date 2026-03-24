"""
Timeout management for resilient operations.

Provides timeout management with configurable timeouts per operation,
cascading timeout propagation, and adaptive timeout adjustment.

Example:
    ```python
    from yoda_foundation.resilience.timeout import (
        TimeoutManager,
        AdaptiveTimeout,
        TimeoutConfig,
    )

    # Create timeout manager
    timeout_manager = TimeoutManager()

    # Register operation timeouts
    timeout_manager.register(
        operation="api_call",
        timeout_ms=5000,
    )

    # Execute with timeout
    result = await timeout_manager.execute_with_timeout(
        operation="api_call",
        func=api_call,
        security_context=context,
    )

    # Use adaptive timeout
    adaptive = AdaptiveTimeout(
        initial_timeout_ms=5000,
        min_timeout_ms=1000,
        max_timeout_ms=30000,
    )

    timeout = await adaptive.get_timeout(
        operation="api_call",
        security_context=context,
    )
    ```
"""

from yoda_foundation.resilience.timeout.adaptive_timeout import (
    AdaptiveTimeout,
    AdaptiveTimeoutConfig,
    LatencyStatistics,
)
from yoda_foundation.resilience.timeout.timeout_manager import (
    TimeoutConfig,
    TimeoutManager,
    TimeoutResult,
)


__all__ = [
    "AdaptiveTimeout",
    "AdaptiveTimeoutConfig",
    "LatencyStatistics",
    "TimeoutConfig",
    "TimeoutManager",
    "TimeoutResult",
]
