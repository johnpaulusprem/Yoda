"""
Retry policy for resilient operations.

This module provides configurable retry policies with exponential backoff,
retry budgets, and exception filtering.

Example:
    ```python
    from yoda_foundation.resilience.retry import (
        RetryPolicy,
        ExponentialBackoff,
        RetryBudget,
    )
    from yoda_foundation.security import create_security_context

    # Create retry policy
    policy = RetryPolicy(
        max_attempts=5,
        backoff=ExponentialBackoff(base_delay_ms=100, max_delay_ms=5000),
        retry_budget=RetryBudget(max_retries=100, time_window_seconds=60),
        retryable_exceptions=(ConnectionError, TimeoutError),
    )

    # Execute with retry
    context = create_security_context(user_id="user_123")

    async def risky_operation() -> str:
        # May fail transiently
        return await external_api_call()

    result = await policy.execute(
        func=risky_operation,
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from yoda_foundation.exceptions import (
    RetryBudgetExceededError,
    RetryExhaustedError,
    ValidationError,
)
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.resilience.retry.exponential_backoff import ExponentialBackoff
from yoda_foundation.resilience.retry.retry_budget import RetryBudget
from yoda_foundation.security.context import SecurityContext


T = TypeVar("T")

logger = logging.getLogger(__name__)


@dataclass
class RetryResult:
    """
    Result of retry execution.

    Attributes:
        result: The successful result
        attempts: Number of attempts made
        total_delay_ms: Total retry delay in milliseconds
        exceptions: List of exceptions encountered
        success: Whether operation succeeded

    Example:
        ```python
        result = RetryResult(
            result="success",
            attempts=3,
            total_delay_ms=700,
            exceptions=[error1, error2],
            success=True,
        )
        ```
    """

    result: Any | None = None
    attempts: int = 0
    total_delay_ms: int = 0
    exceptions: list = field(default_factory=list)
    success: bool = False


class RetryPolicy:
    """
    Retry policy with exponential backoff and budget management.

    Executes operations with automatic retry on transient failures,
    using configurable backoff strategy and budget limits.

    Attributes:
        max_attempts: Maximum retry attempts
        backoff: Backoff strategy
        retry_budget: Optional retry budget
        retryable_exceptions: Tuple of exception types to retry
        non_retryable_exceptions: Tuple of exception types to never retry

    Example:
        ```python
        # Create retry policy
        policy = RetryPolicy(
            max_attempts=5,
            backoff=ExponentialBackoff(base_delay_ms=100),
            retryable_exceptions=(ConnectionError, TimeoutError),
        )

        # Execute with retry
        result = await policy.execute(
            func=my_async_function,
            security_context=context,
        )

        # Execute with arguments
        result = await policy.execute(
            func=my_function,
            args=("arg1", "arg2"),
            kwargs={"key": "value"},
            security_context=context,
        )
        ```
    """

    def __init__(
        self,
        max_attempts: int = 3,
        backoff: ExponentialBackoff | None = None,
        retry_budget: RetryBudget | None = None,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
        non_retryable_exceptions: tuple[type[Exception], ...] = (),
    ) -> None:
        """
        Initialize retry policy.

        Args:
            max_attempts: Maximum retry attempts
            backoff: Backoff strategy (creates default if not provided)
            retry_budget: Optional retry budget
            retryable_exceptions: Exception types to retry
            non_retryable_exceptions: Exception types to never retry

        Raises:
            ValidationError: If max_attempts is invalid
        """
        if max_attempts < 1:
            raise ValidationError(
                message=f"max_attempts must be at least 1, got {max_attempts}",
                field_name="max_attempts",
            )

        self.max_attempts = max_attempts
        self.backoff = backoff or ExponentialBackoff()
        self.retry_budget = retry_budget
        self.retryable_exceptions = retryable_exceptions
        self.non_retryable_exceptions = non_retryable_exceptions

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        security_context: SecurityContext,
        args: tuple[Any, ...] = (),
        kwargs: dict | None = None,
        operation_name: str | None = None,
    ) -> T:
        """
        Execute function with retry policy.

        Args:
            func: Async function to execute
            security_context: Security context
            args: Positional arguments for function
            kwargs: Keyword arguments for function
            operation_name: Optional operation name for logging

        Returns:
            Function result

        Raises:
            RetryExhaustedError: If all retry attempts exhausted
            RetryBudgetExceededError: If retry budget exceeded
            Exception: If non-retryable exception encountered

        Example:
            ```python
            # Simple execution
            result = await policy.execute(
                func=my_function,
                security_context=context,
            )

            # With arguments
            result = await policy.execute(
                func=my_function,
                args=("arg1",),
                kwargs={"key": "value"},
                security_context=context,
            )
            ```
        """
        kwargs = kwargs or {}
        operation_name = operation_name or func.__name__

        exceptions_encountered = []
        total_delay_ms = 0
        last_exception = None

        for attempt in range(self.max_attempts):
            try:
                # Check retry budget before attempt
                if self.retry_budget and attempt > 0:
                    if not await self.retry_budget.can_retry(security_context):
                        raise RetryBudgetExceededError(
                            current_retries=await self._get_budget_used(security_context),
                            budget_limit=self.retry_budget.max_retries,
                            time_window=f"{self.retry_budget.time_window_seconds} seconds",
                        )
                    await self.retry_budget.consume(security_context)

                # Execute function
                result = await func(*args, **kwargs)

                # Success - reset budget if configured
                if self.retry_budget and attempt > 0:
                    await self.retry_budget.reset(security_context)

                # Log successful retry
                if attempt > 0:
                    logger.info(
                        f"Operation '{operation_name}' succeeded after {attempt + 1} attempts",
                        extra={
                            "operation": operation_name,
                            "attempts": attempt + 1,
                            "total_delay_ms": total_delay_ms,
                        },
                    )

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
                last_exception = e
                exceptions_encountered.append(e)

                # Check if exception is retryable
                if not self._is_retryable(e):
                    logger.warning(
                        f"Non-retryable exception for operation '{operation_name}'",
                        extra={
                            "operation": operation_name,
                            "exception": str(e),
                            "exception_type": type(e).__name__,
                        },
                    )
                    raise

                # Check if we have more attempts
                if attempt + 1 >= self.max_attempts:
                    # Out of attempts
                    break

                # Calculate backoff delay
                delay_ms = self.backoff.get_delay(attempt)
                total_delay_ms += delay_ms

                logger.warning(
                    f"Retry attempt {attempt + 1}/{self.max_attempts} for '{operation_name}'",
                    extra={
                        "operation": operation_name,
                        "attempt": attempt + 1,
                        "max_attempts": self.max_attempts,
                        "delay_ms": delay_ms,
                        "exception": str(e),
                    },
                )

                # Wait before retry
                await asyncio.sleep(delay_ms / 1000.0)

        # All retries exhausted
        raise RetryExhaustedError(
            operation=operation_name,
            attempts=self.max_attempts,
            max_attempts=self.max_attempts,
            last_error=last_exception,
            details={
                "total_delay_ms": total_delay_ms,
                "exceptions": [str(e) for e in exceptions_encountered],
            },
        )

    def _is_retryable(self, exception: Exception) -> bool:
        """
        Check if exception is retryable.

        Args:
            exception: Exception to check

        Returns:
            True if exception should be retried
        """
        # Never retry non-retryable exceptions
        if isinstance(exception, self.non_retryable_exceptions):
            return False

        # Check if it's a retryable exception
        return isinstance(exception, self.retryable_exceptions)

    async def _get_budget_used(self, security_context: SecurityContext) -> int:
        """
        Get current retry budget usage.

        Args:
            security_context: Security context

        Returns:
            Number of retries used
        """
        if not self.retry_budget:
            return 0

        stats = await self.retry_budget.get_statistics(security_context)
        return stats["used"]

    async def execute_with_result(
        self,
        func: Callable[..., Awaitable[T]],
        security_context: SecurityContext,
        args: tuple[Any, ...] = (),
        kwargs: dict | None = None,
        operation_name: str | None = None,
    ) -> RetryResult:
        """
        Execute function and return detailed retry result.

        Args:
            func: Async function to execute
            security_context: Security context
            args: Positional arguments for function
            kwargs: Keyword arguments for function
            operation_name: Optional operation name

        Returns:
            RetryResult with detailed execution information

        Example:
            ```python
            result = await policy.execute_with_result(
                func=my_function,
                security_context=context,
            )

            if result.success:
                print(f"Succeeded after {result.attempts} attempts")
                print(f"Total delay: {result.total_delay_ms}ms")
            ```
        """
        try:
            value = await self.execute(
                func=func,
                security_context=security_context,
                args=args,
                kwargs=kwargs,
                operation_name=operation_name,
            )

            return RetryResult(
                result=value,
                attempts=1,  # Will be updated if retries occurred
                success=True,
            )

        except RetryExhaustedError as e:
            return RetryResult(
                result=None,
                attempts=e.attempts,
                total_delay_ms=e.details.get("total_delay_ms", 0),
                exceptions=e.details.get("exceptions", []),
                success=False,
            )

    def __repr__(self) -> str:
        """Return string representation."""
        return f"RetryPolicy(max_attempts={self.max_attempts}, backoff={self.backoff})"
