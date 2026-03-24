"""
Health monitoring for circuit breakers.

This module provides health monitoring to track failure rates and
trigger circuit breaker state changes.

Example:
    ```python
    from yoda_foundation.resilience.circuit_breaker import HealthMonitor

    monitor = HealthMonitor(
        window_size_seconds=60,
        failure_rate_threshold=0.5,
    )

    # Record result
    await monitor.record_result(
        success=False,
        security_context=context,
    )

    # Check health
    is_healthy = await monitor.is_healthy(security_context=context)
    ```
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from yoda_foundation.security.context import SecurityContext


@dataclass
class HealthMetrics:
    """
    Health metrics for circuit breaker monitoring.

    Attributes:
        total_calls: Total number of calls in the window.
        successful_calls: Number of successful calls.
        failed_calls: Number of failed calls.
        success_rate: Ratio of successful to total calls.
        failure_rate: Ratio of failed to total calls.
        is_healthy: Whether the system is considered healthy.
    """

    total_calls: int
    successful_calls: int
    failed_calls: int
    success_rate: float
    failure_rate: float
    is_healthy: bool


class HealthMonitor:
    """
    Monitor health and failure rates.

    Tracks success/failure rates over a sliding time window
    to determine system health.

    Attributes:
        window_size_seconds: Time window for metric calculations.
        failure_rate_threshold: Failure rate considered unhealthy.
        min_calls: Minimum calls before rate calculations apply.

    Example:
        ```python
        monitor = HealthMonitor(
            window_size_seconds=60,
            failure_rate_threshold=0.5,
        )

        # Record operations
        await monitor.record_result(success=True, security_context=ctx)
        await monitor.record_result(success=False, security_context=ctx)

        # Get metrics
        metrics = await monitor.get_metrics(security_context=ctx)
        print(f"Failure rate: {metrics.failure_rate:.2%}")
        ```
    """

    def __init__(
        self,
        window_size_seconds: int = 60,
        failure_rate_threshold: float = 0.5,
        min_calls: int = 10,
    ) -> None:
        """
        Initialize health monitor.

        Args:
            window_size_seconds: Time window for metrics
            failure_rate_threshold: Failure rate to consider unhealthy
            min_calls: Minimum calls before calculating rates
        """
        self.window_size_seconds = window_size_seconds
        self.failure_rate_threshold = failure_rate_threshold
        self.min_calls = min_calls

        self._results: deque[tuple[datetime, bool]] = deque()
        self._lock = asyncio.Lock()

    async def record_result(
        self,
        success: bool,
        security_context: SecurityContext,
    ) -> None:
        """
        Record operation result.

        Args:
            success: Whether operation succeeded
            security_context: Security context
        """
        async with self._lock:
            now = datetime.now(UTC)
            self._results.append((now, success))
            self._cleanup_old_results()

    async def is_healthy(
        self,
        security_context: SecurityContext,
    ) -> bool:
        """
        Check if system is healthy.

        Args:
            security_context: Security context

        Returns:
            True if healthy
        """
        metrics = await self.get_metrics(security_context)
        return metrics.is_healthy

    async def get_metrics(
        self,
        security_context: SecurityContext,
    ) -> HealthMetrics:
        """
        Get health metrics.

        Args:
            security_context: Security context

        Returns:
            HealthMetrics with current health statistics
        """
        async with self._lock:
            self._cleanup_old_results()

            total = len(self._results)
            if total == 0:
                return HealthMetrics(
                    total_calls=0,
                    successful_calls=0,
                    failed_calls=0,
                    success_rate=1.0,
                    failure_rate=0.0,
                    is_healthy=True,
                )

            successful = sum(1 for _, success in self._results if success)
            failed = total - successful

            success_rate = successful / total if total > 0 else 0.0
            failure_rate = failed / total if total > 0 else 0.0

            # Consider healthy if failure rate below threshold and min calls met
            is_healthy = failure_rate < self.failure_rate_threshold or total < self.min_calls

            return HealthMetrics(
                total_calls=total,
                successful_calls=successful,
                failed_calls=failed,
                success_rate=success_rate,
                failure_rate=failure_rate,
                is_healthy=is_healthy,
            )

    def _cleanup_old_results(self) -> None:
        """
        Remove results outside the configured time window.

        Purges health check results that are older than the configured
        window_size_seconds from the internal results deque. This method
        maintains a sliding window of recent results for accurate rate
        calculations.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=self.window_size_seconds)

        while self._results and self._results[0][0] < cutoff:
            self._results.popleft()
