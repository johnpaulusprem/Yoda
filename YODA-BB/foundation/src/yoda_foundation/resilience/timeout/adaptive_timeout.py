"""
Adaptive timeout with dynamic adjustment.

This module provides adaptive timeout management that adjusts timeouts
based on historical latency patterns.

Example:
    ```python
    from yoda_foundation.resilience.timeout import AdaptiveTimeout

    # Create adaptive timeout
    adaptive = AdaptiveTimeout(
        initial_timeout_ms=5000,
        min_timeout_ms=1000,
        max_timeout_ms=30000,
        percentile=95,
    )

    # Record latencies
    await adaptive.record_latency(
        operation="api_call",
        latency_ms=1500,
        security_context=context,
    )

    # Get adaptive timeout
    timeout = await adaptive.get_timeout(
        operation="api_call",
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import (
    Any,
    TypeVar,
)

from yoda_foundation.exceptions import ValidationError
from yoda_foundation.security.context import SecurityContext


T = TypeVar("T")

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveTimeoutConfig:
    """
    Configuration for adaptive timeout.

    Attributes:
        initial_timeout_ms: Initial timeout value
        min_timeout_ms: Minimum allowed timeout
        max_timeout_ms: Maximum allowed timeout
        percentile: Percentile for timeout calculation (e.g., 95)
        window_size: Number of samples to keep
        window_duration_seconds: Duration to keep samples
        adjustment_factor: Factor to apply on top of percentile
        enabled: Whether adaptive timeout is enabled

    Example:
        ```python
        config = AdaptiveTimeoutConfig(
            initial_timeout_ms=5000,
            min_timeout_ms=1000,
            max_timeout_ms=30000,
            percentile=95,
            window_size=100,
        )
        ```
    """

    initial_timeout_ms: int = 5000
    min_timeout_ms: int = 1000
    max_timeout_ms: int = 60000
    percentile: float = 95.0
    window_size: int = 100
    window_duration_seconds: int = 300
    adjustment_factor: float = 1.2
    enabled: bool = True


@dataclass
class LatencySample:
    """
    A latency sample with timestamp.

    Attributes:
        latency_ms: Latency in milliseconds
        timestamp: When the sample was recorded
        success: Whether the operation succeeded

    Example:
        ```python
        sample = LatencySample(
            latency_ms=1500,
            timestamp=datetime.now(timezone.utc),
            success=True,
        )
        ```
    """

    latency_ms: float
    timestamp: datetime
    success: bool = True


@dataclass
class LatencyStatistics:
    """
    Statistics for latency samples.

    Attributes:
        operation: Operation name
        sample_count: Number of samples
        min_latency_ms: Minimum latency
        max_latency_ms: Maximum latency
        mean_latency_ms: Mean latency
        median_latency_ms: Median latency
        p95_latency_ms: 95th percentile latency
        p99_latency_ms: 99th percentile latency
        std_dev_ms: Standard deviation
        current_timeout_ms: Current adaptive timeout
        success_rate: Operation success rate

    Example:
        ```python
        stats = await adaptive.get_statistics(
            operation="api_call",
            security_context=context,
        )
        print(f"P95 latency: {stats.p95_latency_ms:.0f}ms")
        print(f"Current timeout: {stats.current_timeout_ms}ms")
        ```
    """

    operation: str
    sample_count: int
    min_latency_ms: float
    max_latency_ms: float
    mean_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    std_dev_ms: float
    current_timeout_ms: int
    success_rate: float


class AdaptiveTimeout:
    """
    Adaptive timeout with dynamic adjustment.

    Adjusts timeouts based on historical latency patterns using
    percentile-based calculation.

    Attributes:
        config: Adaptive timeout configuration

    Example:
        ```python
        adaptive = AdaptiveTimeout(
            initial_timeout_ms=5000,
            min_timeout_ms=1000,
            max_timeout_ms=30000,
            percentile=95,
        )

        # Execute operations and record latencies
        for _ in range(100):
            start = time.time()
            result = await api_call()
            latency_ms = (time.time() - start) * 1000

            await adaptive.record_latency(
                operation="api_call",
                latency_ms=latency_ms,
                security_context=context,
            )

        # Get adaptive timeout
        timeout = await adaptive.get_timeout(
            operation="api_call",
            security_context=context,
        )
        print(f"Adaptive timeout: {timeout}ms")
        ```
    """

    def __init__(
        self,
        initial_timeout_ms: int = 5000,
        min_timeout_ms: int = 1000,
        max_timeout_ms: int = 60000,
        percentile: float = 95.0,
        window_size: int = 100,
        window_duration_seconds: int = 300,
        adjustment_factor: float = 1.2,
    ) -> None:
        """
        Initialize adaptive timeout.

        Args:
            initial_timeout_ms: Initial timeout value
            min_timeout_ms: Minimum allowed timeout
            max_timeout_ms: Maximum allowed timeout
            percentile: Percentile for timeout calculation
            window_size: Number of samples to keep
            window_duration_seconds: Duration to keep samples
            adjustment_factor: Factor to apply on top of percentile

        Raises:
            ValidationError: If parameters are invalid
        """
        if min_timeout_ms <= 0:
            raise ValidationError(
                message=f"min_timeout_ms must be positive, got {min_timeout_ms}",
                field_name="min_timeout_ms",
            )

        if max_timeout_ms < min_timeout_ms:
            raise ValidationError(
                message=f"max_timeout_ms ({max_timeout_ms}) must be >= min_timeout_ms ({min_timeout_ms})",
                field_name="max_timeout_ms",
            )

        if not 0 < percentile <= 100:
            raise ValidationError(
                message=f"percentile must be between 0 and 100, got {percentile}",
                field_name="percentile",
            )

        if adjustment_factor < 1.0:
            raise ValidationError(
                message=f"adjustment_factor must be >= 1.0, got {adjustment_factor}",
                field_name="adjustment_factor",
            )

        self.config = AdaptiveTimeoutConfig(
            initial_timeout_ms=initial_timeout_ms,
            min_timeout_ms=min_timeout_ms,
            max_timeout_ms=max_timeout_ms,
            percentile=percentile,
            window_size=window_size,
            window_duration_seconds=window_duration_seconds,
            adjustment_factor=adjustment_factor,
        )

        # Per-operation samples
        self._samples: dict[str, deque[LatencySample]] = {}
        self._current_timeouts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def record_latency(
        self,
        operation: str,
        latency_ms: float,
        security_context: SecurityContext,
        success: bool = True,
    ) -> None:
        """
        Record a latency sample for an operation.

        Args:
            operation: Operation name
            latency_ms: Latency in milliseconds
            security_context: Security context
            success: Whether the operation succeeded

        Example:
            ```python
            start = time.time()
            result = await api_call()
            latency_ms = (time.time() - start) * 1000

            await adaptive.record_latency(
                operation="api_call",
                latency_ms=latency_ms,
                success=True,
                security_context=context,
            )
            ```
        """
        sample = LatencySample(
            latency_ms=latency_ms,
            timestamp=datetime.now(UTC),
            success=success,
        )

        async with self._lock:
            if operation not in self._samples:
                self._samples[operation] = deque(maxlen=self.config.window_size)
                self._current_timeouts[operation] = self.config.initial_timeout_ms

            self._samples[operation].append(sample)

            # Prune old samples
            await self._prune_old_samples(operation)

            # Recalculate timeout
            await self._recalculate_timeout(operation)

        logger.debug(
            f"Recorded latency for '{operation}': {latency_ms:.0f}ms (success={success})",
            extra={
                "operation": operation,
                "latency_ms": latency_ms,
                "success": success,
            },
        )

    async def get_timeout(
        self,
        operation: str,
        security_context: SecurityContext,
    ) -> int:
        """
        Get adaptive timeout for an operation.

        Args:
            operation: Operation name
            security_context: Security context

        Returns:
            Timeout in milliseconds

        Example:
            ```python
            timeout = await adaptive.get_timeout(
                operation="api_call",
                security_context=context,
            )
            print(f"Use timeout: {timeout}ms")
            ```
        """
        async with self._lock:
            if operation not in self._current_timeouts:
                return self.config.initial_timeout_ms

            return self._current_timeouts[operation]

    async def execute_with_adaptive_timeout(
        self,
        operation: str,
        func: Callable[..., Awaitable[T]],
        security_context: SecurityContext,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> T:
        """
        Execute function with adaptive timeout and automatic latency recording.

        Args:
            operation: Operation name
            func: Async function to execute
            security_context: Security context
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            asyncio.TimeoutError: If operation times out
            Exception: If function raises exception

        Example:
            ```python
            result = await adaptive.execute_with_adaptive_timeout(
                operation="api_call",
                func=api_call,
                args=(endpoint,),
                security_context=context,
            )
            ```
        """
        kwargs = kwargs or {}

        timeout_ms = await self.get_timeout(operation, security_context)
        timeout_seconds = timeout_ms / 1000.0

        start_time = datetime.now(UTC)
        success = False

        try:
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout_seconds,
            )
            success = True
            return result

        except TimeoutError:
            logger.warning(
                f"Operation '{operation}' timed out with adaptive timeout {timeout_ms}ms",
                extra={"operation": operation, "timeout_ms": timeout_ms},
            )
            raise

        finally:
            elapsed_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            await self.record_latency(
                operation=operation,
                latency_ms=elapsed_ms,
                security_context=security_context,
                success=success,
            )

    async def get_statistics(
        self,
        operation: str,
        security_context: SecurityContext,
    ) -> LatencyStatistics | None:
        """
        Get latency statistics for an operation.

        Args:
            operation: Operation name
            security_context: Security context

        Returns:
            LatencyStatistics or None if no samples

        Example:
            ```python
            stats = await adaptive.get_statistics(
                operation="api_call",
                security_context=context,
            )
            if stats:
                print(f"P95: {stats.p95_latency_ms:.0f}ms")
                print(f"Current timeout: {stats.current_timeout_ms}ms")
            ```
        """
        async with self._lock:
            if operation not in self._samples or not self._samples[operation]:
                return None

            samples = list(self._samples[operation])
            latencies = [s.latency_ms for s in samples]
            successful = sum(1 for s in samples if s.success)

            if not latencies:
                return None

            sorted_latencies = sorted(latencies)

            return LatencyStatistics(
                operation=operation,
                sample_count=len(samples),
                min_latency_ms=min(latencies),
                max_latency_ms=max(latencies),
                mean_latency_ms=statistics.mean(latencies),
                median_latency_ms=statistics.median(latencies),
                p95_latency_ms=self._percentile(sorted_latencies, 95),
                p99_latency_ms=self._percentile(sorted_latencies, 99),
                std_dev_ms=statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
                current_timeout_ms=self._current_timeouts.get(
                    operation, self.config.initial_timeout_ms
                ),
                success_rate=successful / len(samples) if samples else 0.0,
            )

    async def reset(
        self,
        security_context: SecurityContext,
        operation: str | None = None,
    ) -> None:
        """
        Reset adaptive timeout data.

        Args:
            security_context: Security context
            operation: Optional operation filter

        Example:
            ```python
            # Reset all
            await adaptive.reset(security_context=context)

            # Reset specific operation
            await adaptive.reset(
                security_context=context,
                operation="api_call",
            )
            ```
        """
        security_context.require_permission("resilience.manage_timeout")

        async with self._lock:
            if operation:
                if operation in self._samples:
                    self._samples[operation].clear()
                    self._current_timeouts[operation] = self.config.initial_timeout_ms
            else:
                self._samples.clear()
                self._current_timeouts.clear()

        logger.info(
            "Adaptive timeout reset",
            extra={"operation": operation},
        )

    async def set_baseline(
        self,
        operation: str,
        baseline_timeout_ms: int,
        security_context: SecurityContext,
    ) -> None:
        """
        Set a baseline timeout for an operation.

        Args:
            operation: Operation name
            baseline_timeout_ms: Baseline timeout in milliseconds
            security_context: Security context

        Example:
            ```python
            await adaptive.set_baseline(
                operation="api_call",
                baseline_timeout_ms=5000,
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_timeout")

        clamped = self._clamp_timeout(baseline_timeout_ms)

        async with self._lock:
            self._current_timeouts[operation] = clamped

        logger.info(
            f"Set baseline timeout for '{operation}': {clamped}ms",
            extra={"operation": operation, "timeout_ms": clamped},
        )

    async def get_all_statistics(
        self,
        security_context: SecurityContext,
    ) -> dict[str, LatencyStatistics]:
        """
        Get statistics for all operations.

        Args:
            security_context: Security context

        Returns:
            Dictionary mapping operation names to statistics

        Example:
            ```python
            all_stats = await adaptive.get_all_statistics(security_context=context)
            for op, stats in all_stats.items():
                print(f"{op}: P95={stats.p95_latency_ms:.0f}ms")
            ```
        """
        result = {}
        for operation in self._samples.keys():
            stats = await self.get_statistics(operation, security_context)
            if stats:
                result[operation] = stats
        return result

    async def _prune_old_samples(self, operation: str) -> None:
        """
        Prune samples older than the configured window duration.

        Removes latency samples that are older than window_duration_seconds
        to maintain a sliding window of recent samples for accurate
        timeout calculations.

        Args:
            operation: The operation name whose samples to prune.
        """
        if operation not in self._samples:
            return

        cutoff = datetime.now(UTC) - timedelta(seconds=self.config.window_duration_seconds)

        samples = self._samples[operation]
        while samples and samples[0].timestamp < cutoff:
            samples.popleft()

    async def _recalculate_timeout(self, operation: str) -> None:
        """
        Recalculate adaptive timeout based on current samples.

        Calculates a new timeout value using the configured percentile
        of successful latency samples, applies the adjustment factor,
        and clamps to min/max bounds. Logs significant timeout changes.

        Args:
            operation: The operation name to recalculate timeout for.
        """
        if operation not in self._samples:
            return

        samples = self._samples[operation]
        if not samples:
            self._current_timeouts[operation] = self.config.initial_timeout_ms
            return

        # Only use successful samples for timeout calculation
        successful_latencies = [s.latency_ms for s in samples if s.success]

        if not successful_latencies:
            # No successful samples, use initial timeout
            self._current_timeouts[operation] = self.config.initial_timeout_ms
            return

        # Calculate percentile
        sorted_latencies = sorted(successful_latencies)
        percentile_latency = self._percentile(sorted_latencies, self.config.percentile)

        # Apply adjustment factor
        adjusted_timeout = int(percentile_latency * self.config.adjustment_factor)

        # Clamp to min/max
        clamped_timeout = self._clamp_timeout(adjusted_timeout)

        old_timeout = self._current_timeouts.get(operation, self.config.initial_timeout_ms)
        self._current_timeouts[operation] = clamped_timeout

        if clamped_timeout != old_timeout:
            logger.info(
                f"Adaptive timeout for '{operation}' adjusted: {old_timeout}ms -> {clamped_timeout}ms "
                f"(P{self.config.percentile}={percentile_latency:.0f}ms)",
                extra={
                    "operation": operation,
                    "old_timeout_ms": old_timeout,
                    "new_timeout_ms": clamped_timeout,
                    "percentile_latency_ms": percentile_latency,
                },
            )

    def _percentile(self, sorted_data: list[float], percentile: float) -> float:
        """
        Calculate percentile from sorted data using linear interpolation.

        Uses the linear interpolation method to calculate percentile
        values from a sorted list of floats.

        Args:
            sorted_data: Pre-sorted list of float values.
            percentile: Percentile to calculate (0-100).

        Returns:
            The calculated percentile value.
        """
        if not sorted_data:
            return 0.0

        if len(sorted_data) == 1:
            return sorted_data[0]

        # Linear interpolation
        k = (len(sorted_data) - 1) * (percentile / 100.0)
        f = math.floor(k)
        c = math.ceil(k)

        if f == c:
            return sorted_data[int(k)]

        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)

        return d0 + d1

    def _clamp_timeout(self, timeout_ms: int) -> int:
        """
        Clamp timeout to configured minimum and maximum bounds.

        Args:
            timeout_ms: The timeout value in milliseconds to clamp.

        Returns:
            Timeout clamped to min_timeout_ms and max_timeout_ms bounds.
        """
        return max(
            self.config.min_timeout_ms,
            min(self.config.max_timeout_ms, timeout_ms),
        )

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"AdaptiveTimeout("
            f"initial={self.config.initial_timeout_ms}ms, "
            f"min={self.config.min_timeout_ms}ms, "
            f"max={self.config.max_timeout_ms}ms, "
            f"percentile={self.config.percentile})"
        )
