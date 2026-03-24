"""
Resilience module for the Agentic AI Component Library.

Provides comprehensive resilience mechanisms for building fault-tolerant
agentic AI systems:

- Retry: Configurable retry policies with exponential backoff and budgets
- Circuit Breaker: Prevent cascading failures with automatic recovery
- Fallback: Chain of fallback strategies with static, cache, and degraded modes
- Bulkhead: Resource isolation to prevent resource exhaustion
- Timeout: Configurable and adaptive timeout management
- Health: Component health monitoring and readiness probes
- Recovery: Automatic recovery procedures and state checkpointing

Example:
    ```python
    from yoda_foundation.resilience import (
        # Retry
        RetryPolicy,
        ExponentialBackoff,
        # Circuit Breaker
        CircuitBreaker,
        # Fallback
        FallbackChain,
        StaticFallback,
        CacheFallback,
        # Bulkhead
        SemaphoreBulkhead,
        # Timeout
        TimeoutManager,
        AdaptiveTimeout,
        # Health
        HealthChecker,
        ReadinessProbe,
        # Recovery
        RecoveryManager,
        CheckpointManager,
    )

    # Configure retry with exponential backoff
    retry_policy = RetryPolicy(
        max_attempts=5,
        backoff=ExponentialBackoff(base_delay_ms=100, max_delay_ms=5000),
    )

    # Use circuit breaker for external calls
    circuit_breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout_ms=30000,
    )

    # Resource isolation with bulkhead
    bulkhead = SemaphoreBulkhead(
        name="api_calls",
        max_concurrent=10,
    )

    # Health monitoring
    health_checker = HealthChecker()
    health_checker.register_check("database", check_database, critical=True)
    ```
"""

# Retry
# Bulkhead
from yoda_foundation.resilience.bulkhead.bulkhead import (
    Bulkhead,
    BulkheadConfig,
    BulkheadRejectedException,
    BulkheadStatistics,
)
from yoda_foundation.resilience.bulkhead.semaphore_bulkhead import (
    SemaphoreBulkhead,
)

# Circuit Breaker
from yoda_foundation.resilience.circuit_breaker.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)
from yoda_foundation.resilience.circuit_breaker.health_monitor import HealthMonitor

# Fallback
from yoda_foundation.resilience.fallback.fallback_chain import FallbackChain
from yoda_foundation.resilience.fallback.fallback_strategies import (
    AlternativeServiceFallback,
    BaseFallbackStrategy,
    CacheFallback,
    DegradedFallback,
    StaticFallback,
)
from yoda_foundation.resilience.fallback.graceful_degradation import GracefulDegradation
from yoda_foundation.resilience.fallback.model_fallback import ModelFallback

# Health
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
from yoda_foundation.resilience.recovery.checkpoint_manager import CheckpointManager
from yoda_foundation.resilience.recovery.recovery_manager import (
    RecoveryManager,
    RecoveryProcedure,
    RecoveryResult,
    RecoveryStatus,
)

# Recovery
from yoda_foundation.resilience.recovery.state_recovery import StateRecovery
from yoda_foundation.resilience.retry.exponential_backoff import ExponentialBackoff
from yoda_foundation.resilience.retry.retry_budget import RetryBudget
from yoda_foundation.resilience.retry.retry_policy import RetryPolicy
from yoda_foundation.resilience.timeout.adaptive_timeout import (
    AdaptiveTimeout,
    AdaptiveTimeoutConfig,
    LatencyStatistics,
)

# Timeout
from yoda_foundation.resilience.timeout.timeout_manager import (
    TimeoutConfig,
    TimeoutManager,
)


__all__ = [
    # Retry
    "RetryPolicy",
    "ExponentialBackoff",
    "RetryBudget",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitState",
    "HealthMonitor",
    # Fallback
    "FallbackChain",
    "ModelFallback",
    "GracefulDegradation",
    "BaseFallbackStrategy",
    "StaticFallback",
    "CacheFallback",
    "DegradedFallback",
    "AlternativeServiceFallback",
    # Bulkhead
    "Bulkhead",
    "BulkheadConfig",
    "BulkheadStatistics",
    "BulkheadRejectedException",
    "SemaphoreBulkhead",
    # Timeout
    "TimeoutManager",
    "TimeoutConfig",
    "AdaptiveTimeout",
    "AdaptiveTimeoutConfig",
    "LatencyStatistics",
    # Health
    "HealthChecker",
    "HealthCheck",
    "HealthCheckResult",
    "HealthStatus",
    "ComponentHealth",
    "ReadinessProbe",
    "ReadinessResult",
    "ReadinessStatus",
    # Recovery
    "StateRecovery",
    "CheckpointManager",
    "RecoveryManager",
    "RecoveryProcedure",
    "RecoveryResult",
    "RecoveryStatus",
]
