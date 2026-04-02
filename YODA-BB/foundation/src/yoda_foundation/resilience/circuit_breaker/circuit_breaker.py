"""
Circuit breaker implementation for fault isolation.

This module provides a circuit breaker pattern implementation to prevent
cascading failures by stopping calls to failing services.

Example:
    ```python
    from yoda_foundation.resilience.circuit_breaker import CircuitBreaker
    from yoda_foundation.security import create_security_context

    # Create circuit breaker
    breaker = CircuitBreaker(
        name="payment_api",
        failure_threshold=5,
        recovery_timeout_ms=30000,
    )

    # Execute with protection
    context = create_security_context(user_id="user_123")
    result = await breaker.execute(
        func=call_payment_api,
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, TypeVar

from yoda_foundation.exceptions import (
    CircuitBreakerOpenError,
    ValidationError,
)
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.security.context import SecurityContext


T = TypeVar("T")

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """
    Circuit breaker states.

    Attributes:
        CLOSED: Normal operation, all requests allowed
        OPEN: Failure threshold exceeded, requests blocked
        HALF_OPEN: Testing recovery, limited requests allowed
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerStats:
    """
    Circuit breaker statistics.

    Attributes:
        state: Current circuit state.
        failure_count: Total failure count.
        success_count: Total success count.
        consecutive_failures: Current consecutive failure count.
        consecutive_successes: Current consecutive success count.
        last_failure_time: Timestamp of last failure.
        last_success_time: Timestamp of last success.
        total_calls: Total number of calls processed.
        rejected_calls: Number of calls rejected due to open circuit.
    """

    state: CircuitState
    failure_count: int
    success_count: int
    consecutive_failures: int
    consecutive_successes: int
    last_failure_time: datetime | None
    last_success_time: datetime | None
    total_calls: int
    rejected_calls: int


class CircuitBreaker:
    """
    Circuit breaker for fault isolation.

    Implements the circuit breaker pattern to prevent cascading failures.
    Transitions between CLOSED, OPEN, and HALF_OPEN states based on
    failure rates and recovery attempts.

    Attributes:
        name: Circuit breaker name
        failure_threshold: Number of failures before opening circuit
        recovery_timeout_ms: Time to wait before attempting recovery
        success_threshold: Number of successes needed to close circuit
        half_open_max_calls: Maximum calls allowed in half-open state

    Example:
        ```python
        breaker = CircuitBreaker(
            name="external_api",
            failure_threshold=5,
            recovery_timeout_ms=30000,
            success_threshold=2,
        )

        # Execute with circuit breaker
        try:
            result = await breaker.execute(
                func=api_call,
                security_context=context,
            )
        except CircuitBreakerOpenError:
            # Circuit is open, use fallback
            result = await fallback_function()
        ```
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout_ms: int = 30000,
        success_threshold: int = 2,
        half_open_max_calls: int = 3,
    ) -> None:
        """
        Initialize circuit breaker.

        Args:
            name: Circuit breaker name
            failure_threshold: Failures before opening circuit
            recovery_timeout_ms: Recovery timeout in milliseconds
            success_threshold: Successes needed to close circuit
            half_open_max_calls: Max calls in half-open state

        Raises:
            ValidationError: If parameters are invalid
        """
        if failure_threshold < 1:
            raise ValidationError(
                message=f"failure_threshold must be at least 1, got {failure_threshold}",
                field_name="failure_threshold",
            )

        if recovery_timeout_ms < 0:
            raise ValidationError(
                message=f"recovery_timeout_ms cannot be negative, got {recovery_timeout_ms}",
                field_name="recovery_timeout_ms",
            )

        if success_threshold < 1:
            raise ValidationError(
                message=f"success_threshold must be at least 1, got {success_threshold}",
                field_name="success_threshold",
            )

        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_ms = recovery_timeout_ms
        self.success_threshold = success_threshold
        self.half_open_max_calls = half_open_max_calls

        # State
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._last_failure_time: datetime | None = None
        self._last_success_time: datetime | None = None
        self._opened_at: datetime | None = None
        self._half_open_calls = 0
        self._total_calls = 0
        self._rejected_calls = 0
        self._lock = asyncio.Lock()

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        security_context: SecurityContext,
        args: tuple[Any, ...] = (),
        kwargs: dict | None = None,
    ) -> T:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            security_context: Security context
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: If function raises exception

        Example:
            ```python
            result = await breaker.execute(
                func=my_function,
                args=("arg1",),
                kwargs={"key": "value"},
                security_context=context,
            )
            ```
        """
        kwargs = kwargs or {}

        async with self._lock:
            self._total_calls += 1

            # Check circuit state
            await self._update_state()

            if self._state == CircuitState.OPEN:
                self._rejected_calls += 1
                raise CircuitBreakerOpenError(
                    circuit_name=self.name,
                    failure_count=self._consecutive_failures,
                    recovery_time=f"{self.recovery_timeout_ms}ms",
                )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    self._rejected_calls += 1
                    raise CircuitBreakerOpenError(
                        circuit_name=self.name,
                        failure_count=self._consecutive_failures,
                        recovery_time="testing recovery",
                    )
                self._half_open_calls += 1

        # Execute function outside lock
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result

        except (
            AgenticBaseException,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
        ) as e:
            await self._on_failure(e)
            raise

    async def _update_state(self) -> None:
        """
        Update circuit state based on recovery timeout conditions.

        Checks if the recovery timeout has elapsed when the circuit is in
        OPEN state and transitions to HALF_OPEN to allow test requests.
        This method should be called before processing each request.
        """
        now = datetime.now(UTC)

        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self._opened_at:
                recovery_time = timedelta(milliseconds=self.recovery_timeout_ms)
                if now - self._opened_at >= recovery_time:
                    logger.info(
                        f"Circuit breaker '{self.name}' entering HALF_OPEN state",
                        extra={"circuit_name": self.name},
                    )
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0

    async def _on_success(self) -> None:
        """
        Handle successful execution and update circuit state.

        Increments success counters, resets consecutive failure count,
        and closes the circuit if enough consecutive successes occur
        while in HALF_OPEN state.
        """
        async with self._lock:
            self._success_count += 1
            self._consecutive_successes += 1
            self._consecutive_failures = 0
            self._last_success_time = datetime.now(UTC)

            if self._state == CircuitState.HALF_OPEN:
                # Check if we can close the circuit
                if self._consecutive_successes >= self.success_threshold:
                    logger.info(
                        f"Circuit breaker '{self.name}' closing after recovery",
                        extra={
                            "circuit_name": self.name,
                            "consecutive_successes": self._consecutive_successes,
                        },
                    )
                    self._state = CircuitState.CLOSED
                    self._half_open_calls = 0

    async def _on_failure(self, exception: Exception) -> None:
        """
        Handle failed execution and update circuit state.

        Increments failure counters and opens the circuit if the failure
        threshold is exceeded while in CLOSED state. Reopens the circuit
        immediately if a failure occurs in HALF_OPEN state.

        Args:
            exception: The exception that caused the failure.
        """
        async with self._lock:
            self._failure_count += 1
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            self._last_failure_time = datetime.now(UTC)

            if self._state == CircuitState.HALF_OPEN:
                # Failure during half-open, reopen circuit
                logger.warning(
                    f"Circuit breaker '{self.name}' reopening after failure in HALF_OPEN",
                    extra={
                        "circuit_name": self.name,
                        "exception": str(exception),
                    },
                )
                self._state = CircuitState.OPEN
                self._opened_at = datetime.now(UTC)

            elif self._state == CircuitState.CLOSED:
                # Check if we should open circuit
                if self._consecutive_failures >= self.failure_threshold:
                    logger.error(
                        f"Circuit breaker '{self.name}' opening after {self._consecutive_failures} failures",
                        extra={
                            "circuit_name": self.name,
                            "consecutive_failures": self._consecutive_failures,
                        },
                    )
                    self._state = CircuitState.OPEN
                    self._opened_at = datetime.now(UTC)

    async def get_state(self) -> CircuitState:
        """
        Get current circuit state after updating based on conditions.

        Returns:
            The current CircuitState (CLOSED, OPEN, or HALF_OPEN).
        """
        async with self._lock:
            await self._update_state()
            return self._state

    async def get_statistics(
        self,
        security_context: SecurityContext,
    ) -> CircuitBreakerStats:
        """
        Get circuit breaker statistics.

        Args:
            security_context: Security context

        Returns:
            CircuitBreakerStats with current statistics

        Example:
            ```python
            stats = await breaker.get_statistics(security_context=context)
            print(f"State: {stats.state.value}")
            print(f"Failures: {stats.consecutive_failures}")
            ```
        """
        async with self._lock:
            await self._update_state()

            return CircuitBreakerStats(
                state=self._state,
                failure_count=self._failure_count,
                success_count=self._success_count,
                consecutive_failures=self._consecutive_failures,
                consecutive_successes=self._consecutive_successes,
                last_failure_time=self._last_failure_time,
                last_success_time=self._last_success_time,
                total_calls=self._total_calls,
                rejected_calls=self._rejected_calls,
            )

    async def reset(
        self,
        security_context: SecurityContext,
    ) -> None:
        """
        Reset circuit breaker to CLOSED state.

        Args:
            security_context: Security context

        Example:
            ```python
            # Manually reset circuit after maintenance
            await breaker.reset(security_context=context)
            ```
        """
        security_context.require_permission("resilience.manage_circuit_breaker")

        async with self._lock:
            logger.info(
                f"Resetting circuit breaker '{self.name}'",
                extra={"circuit_name": self.name},
            )
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            self._half_open_calls = 0
            self._opened_at = None

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"CircuitBreaker("
            f"name={self.name}, "
            f"state={self._state.value}, "
            f"failure_threshold={self.failure_threshold})"
        )
