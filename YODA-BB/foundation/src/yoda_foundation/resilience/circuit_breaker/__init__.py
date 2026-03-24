"""
Circuit breaker pattern for fault isolation.

Provides circuit breaker implementation to prevent cascading failures
by stopping calls to failing services.

Example:
    ```python
    from yoda_foundation.resilience.circuit_breaker import (
        CircuitBreaker,
        CircuitState,
        HealthMonitor,
    )

    # Create circuit breaker
    breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout_ms=30000,
        success_threshold=2,
    )

    # Execute with circuit breaker
    result = await breaker.execute(
        func=external_api_call,
        security_context=context,
    )
    ```
"""

from yoda_foundation.resilience.circuit_breaker.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)
from yoda_foundation.resilience.circuit_breaker.health_monitor import HealthMonitor


__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "HealthMonitor",
]
