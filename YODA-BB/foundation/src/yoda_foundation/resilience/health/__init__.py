"""
Health checking mechanisms for resilient systems.

Provides health checking for components, dependencies, and readiness probes.

Example:
    ```python
    from yoda_foundation.resilience.health import (
        HealthChecker,
        ReadinessProbe,
        HealthStatus,
        HealthCheckResult,
    )

    # Create health checker
    health_checker = HealthChecker()

    # Register component checks
    health_checker.register_check(
        name="database",
        check_func=check_database,
    )
    health_checker.register_check(
        name="cache",
        check_func=check_cache,
    )

    # Check health
    result = await health_checker.check_health(security_context=context)
    print(f"Overall status: {result.status.value}")

    # Use readiness probe
    readiness = ReadinessProbe(health_checker=health_checker)
    is_ready = await readiness.is_ready(security_context=context)
    ```
"""

from yoda_foundation.resilience.health.health_checker import (
    ComponentHealth,
    HealthCheck,
    HealthChecker,
    HealthCheckResult,
    HealthStatus,
)
from yoda_foundation.resilience.health.readiness_probe import (
    ReadinessProbe,
    ReadinessResult,
    ReadinessStatus,
)


__all__ = [
    "ComponentHealth",
    "HealthCheck",
    "HealthCheckResult",
    "HealthChecker",
    "HealthStatus",
    "ReadinessProbe",
    "ReadinessResult",
    "ReadinessStatus",
]
