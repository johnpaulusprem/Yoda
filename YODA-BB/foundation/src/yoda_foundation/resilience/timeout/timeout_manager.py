"""
Timeout manager for operation timeouts.

This module provides configurable timeout management for operations
with cascading timeout propagation support.

Example:
    ```python
    from yoda_foundation.resilience.timeout import TimeoutManager

    # Create timeout manager
    manager = TimeoutManager()

    # Register operation timeouts
    manager.register("api_call", timeout_ms=5000)
    manager.register("db_query", timeout_ms=3000)

    # Execute with timeout
    result = await manager.execute_with_timeout(
        operation="api_call",
        func=api_call,
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import builtins
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import (
    Any,
    Generic,
    TypeVar,
)

from yoda_foundation.exceptions import (
    ResilienceError,
    ValidationError,
)
from yoda_foundation.security.context import SecurityContext


T = TypeVar("T")

logger = logging.getLogger(__name__)


class TimeoutError(ResilienceError):
    """
    Timeout error for operation timeout.

    Attributes:
        operation: The operation that timed out
        timeout_ms: The timeout value in milliseconds
        elapsed_ms: Actual elapsed time

    Example:
        ```python
        try:
            result = await manager.execute_with_timeout(...)
        except TimeoutError as e:
            logger.warning(f"Operation {e.operation} timed out after {e.elapsed_ms}ms")
        ```
    """

    def __init__(
        self,
        operation: str,
        timeout_ms: int,
        elapsed_ms: float | None = None,
        message: str | None = None,
    ) -> None:
        """
        Initialize timeout error.

        Args:
            operation: The operation that timed out
            timeout_ms: The timeout value in milliseconds
            elapsed_ms: Actual elapsed time
            message: Optional custom message
        """
        self.operation = operation
        self.timeout_ms = timeout_ms
        self.elapsed_ms = elapsed_ms

        if not message:
            message = f"Operation '{operation}' timed out after {timeout_ms}ms"
            if elapsed_ms:
                message = f"Operation '{operation}' timed out after {elapsed_ms:.0f}ms (limit: {timeout_ms}ms)"

        super().__init__(
            message=message,
            operation=operation,
            component="timeout",
            suggestions=[
                "Increase timeout if appropriate",
                "Check operation performance",
                "Consider breaking into smaller operations",
            ],
            details={
                "operation": operation,
                "timeout_ms": timeout_ms,
                "elapsed_ms": elapsed_ms,
            },
            retryable=True,
        )


@dataclass
class TimeoutConfig:
    """
    Configuration for operation timeout.

    Attributes:
        operation: Operation name
        timeout_ms: Timeout in milliseconds
        enabled: Whether timeout is enabled
        propagate_remaining: Whether to propagate remaining time to sub-operations
        metadata: Additional configuration metadata

    Example:
        ```python
        config = TimeoutConfig(
            operation="api_call",
            timeout_ms=5000,
            propagate_remaining=True,
        )
        ```
    """

    operation: str
    timeout_ms: int
    enabled: bool = True
    propagate_remaining: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimeoutResult(Generic[T]):
    """
    Result of timeout-protected execution.

    Attributes:
        result: The operation result
        operation: Operation name
        elapsed_ms: Actual execution time
        timeout_ms: Configured timeout
        remaining_ms: Remaining time after execution
        timed_out: Whether operation timed out

    Example:
        ```python
        result = await manager.execute_with_timeout(...)
        print(f"Completed in {result.elapsed_ms:.0f}ms")
        print(f"Remaining: {result.remaining_ms:.0f}ms")
        ```
    """

    result: Any
    operation: str
    elapsed_ms: float
    timeout_ms: int
    remaining_ms: float
    timed_out: bool = False


class TimeoutManager:
    """
    Manager for operation timeouts.

    Provides configurable timeouts per operation with support for
    cascading timeout propagation.

    Attributes:
        default_timeout_ms: Default timeout for unregistered operations

    Example:
        ```python
        manager = TimeoutManager(default_timeout_ms=10000)

        # Register specific timeouts
        manager.register("fast_api", timeout_ms=1000)
        manager.register("slow_api", timeout_ms=30000)

        # Execute with timeout
        result = await manager.execute_with_timeout(
            operation="fast_api",
            func=fast_api_call,
            security_context=context,
        )

        # Use cascading timeout
        async def nested_operation():
            # Get remaining timeout for sub-operations
            remaining = manager.get_remaining_timeout()
            return await sub_operation(timeout_ms=remaining)

        await manager.execute_with_timeout(
            operation="parent",
            func=nested_operation,
            security_context=context,
        )
        ```
    """

    def __init__(
        self,
        default_timeout_ms: int = 30000,
    ) -> None:
        """
        Initialize timeout manager.

        Args:
            default_timeout_ms: Default timeout in milliseconds

        Raises:
            ValidationError: If default_timeout_ms is invalid
        """
        if default_timeout_ms <= 0:
            raise ValidationError(
                message=f"default_timeout_ms must be positive, got {default_timeout_ms}",
                field_name="default_timeout_ms",
            )

        self.default_timeout_ms = default_timeout_ms
        self._configs: dict[str, TimeoutConfig] = {}
        self._lock = asyncio.Lock()

        # Context variable for cascading timeouts
        self._timeout_context: tuple[datetime, int] | None = None

        # Statistics
        self._stats: dict[str, dict[str, Any]] = {}

    def register(
        self,
        operation: str,
        timeout_ms: int,
        enabled: bool = True,
        propagate_remaining: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Register timeout configuration for an operation.

        Args:
            operation: Operation name
            timeout_ms: Timeout in milliseconds
            enabled: Whether timeout is enabled
            propagate_remaining: Whether to propagate remaining time
            metadata: Additional metadata

        Example:
            ```python
            manager.register(
                operation="api_call",
                timeout_ms=5000,
                propagate_remaining=True,
            )
            ```
        """
        if timeout_ms <= 0:
            raise ValidationError(
                message=f"timeout_ms must be positive, got {timeout_ms}",
                field_name="timeout_ms",
            )

        self._configs[operation] = TimeoutConfig(
            operation=operation,
            timeout_ms=timeout_ms,
            enabled=enabled,
            propagate_remaining=propagate_remaining,
            metadata=metadata or {},
        )

        # Initialize stats
        self._stats[operation] = {
            "total_executions": 0,
            "timeouts": 0,
            "total_elapsed_ms": 0.0,
            "min_elapsed_ms": float("inf"),
            "max_elapsed_ms": 0.0,
        }

        logger.debug(
            f"Registered timeout for operation '{operation}': {timeout_ms}ms",
            extra={"operation": operation, "timeout_ms": timeout_ms},
        )

    def unregister(
        self,
        operation: str,
        security_context: SecurityContext,
    ) -> None:
        """
        Unregister timeout configuration.

        Args:
            operation: Operation name
            security_context: Security context

        Example:
            ```python
            manager.unregister(
                operation="deprecated_api",
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_timeout")

        if operation in self._configs:
            del self._configs[operation]
            logger.info(
                f"Unregistered timeout for operation '{operation}'",
                extra={"operation": operation},
            )

    async def execute_with_timeout(
        self,
        operation: str,
        func: Callable[..., Awaitable[T]],
        security_context: SecurityContext,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> T:
        """
        Execute function with timeout protection.

        Args:
            operation: Operation name
            func: Async function to execute
            security_context: Security context
            args: Positional arguments
            kwargs: Keyword arguments
            timeout_ms: Optional timeout override

        Returns:
            Function result

        Raises:
            TimeoutError: If operation times out
            Exception: If function raises exception

        Example:
            ```python
            result = await manager.execute_with_timeout(
                operation="api_call",
                func=api_call,
                args=(endpoint,),
                kwargs={"params": params},
                security_context=context,
            )
            ```
        """
        kwargs = kwargs or {}

        # Get effective timeout
        effective_timeout_ms = self._get_effective_timeout(operation, timeout_ms)

        if effective_timeout_ms is None:
            # Timeout disabled, execute without timeout
            return await func(*args, **kwargs)

        # Check remaining timeout from parent context
        remaining_timeout_ms = self._get_remaining_from_context()
        if remaining_timeout_ms is not None:
            effective_timeout_ms = min(effective_timeout_ms, remaining_timeout_ms)

        timeout_seconds = effective_timeout_ms / 1000.0
        start_time = datetime.now(UTC)

        # Set context for nested operations
        old_context = self._timeout_context
        self._timeout_context = (start_time, effective_timeout_ms)

        try:
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=timeout_seconds,
            )

            elapsed_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            # Update statistics
            await self._update_stats(operation, elapsed_ms, timed_out=False)

            logger.debug(
                f"Operation '{operation}' completed in {elapsed_ms:.0f}ms (limit: {effective_timeout_ms}ms)",
                extra={
                    "operation": operation,
                    "elapsed_ms": elapsed_ms,
                    "timeout_ms": effective_timeout_ms,
                },
            )

            return result

        except builtins.TimeoutError:
            elapsed_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            # Update statistics
            await self._update_stats(operation, elapsed_ms, timed_out=True)

            logger.warning(
                f"Operation '{operation}' timed out after {elapsed_ms:.0f}ms (limit: {effective_timeout_ms}ms)",
                extra={
                    "operation": operation,
                    "elapsed_ms": elapsed_ms,
                    "timeout_ms": effective_timeout_ms,
                },
            )

            raise TimeoutError(
                operation=operation,
                timeout_ms=effective_timeout_ms,
                elapsed_ms=elapsed_ms,
            )

        finally:
            self._timeout_context = old_context

    async def execute_with_result(
        self,
        operation: str,
        func: Callable[..., Awaitable[T]],
        security_context: SecurityContext,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> TimeoutResult:
        """
        Execute function and return detailed timeout result.

        Args:
            operation: Operation name
            func: Async function to execute
            security_context: Security context
            args: Positional arguments
            kwargs: Keyword arguments
            timeout_ms: Optional timeout override

        Returns:
            TimeoutResult with detailed execution information

        Example:
            ```python
            result = await manager.execute_with_result(
                operation="api_call",
                func=api_call,
                security_context=context,
            )
            print(f"Completed in {result.elapsed_ms:.0f}ms")
            print(f"Remaining: {result.remaining_ms:.0f}ms")
            ```
        """
        kwargs = kwargs or {}
        effective_timeout_ms = self._get_effective_timeout(operation, timeout_ms)
        start_time = datetime.now(UTC)

        try:
            if effective_timeout_ms is None:
                value = await func(*args, **kwargs)
                elapsed_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

                return TimeoutResult(
                    result=value,
                    operation=operation,
                    elapsed_ms=elapsed_ms,
                    timeout_ms=0,
                    remaining_ms=float("inf"),
                    timed_out=False,
                )

            value = await self.execute_with_timeout(
                operation=operation,
                func=func,
                security_context=security_context,
                args=args,
                kwargs=kwargs,
                timeout_ms=timeout_ms,
            )

            elapsed_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            remaining_ms = max(0, effective_timeout_ms - elapsed_ms)

            return TimeoutResult(
                result=value,
                operation=operation,
                elapsed_ms=elapsed_ms,
                timeout_ms=effective_timeout_ms,
                remaining_ms=remaining_ms,
                timed_out=False,
            )

        except TimeoutError as e:
            return TimeoutResult(
                result=None,
                operation=operation,
                elapsed_ms=e.elapsed_ms or effective_timeout_ms,
                timeout_ms=effective_timeout_ms,
                remaining_ms=0,
                timed_out=True,
            )

    def get_remaining_timeout(self) -> int | None:
        """
        Get remaining timeout from current context.

        Returns:
            Remaining timeout in milliseconds, or None if no context

        Example:
            ```python
            async def nested_operation():
                remaining = manager.get_remaining_timeout()
                if remaining and remaining < 1000:
                    # Not enough time, skip expensive operation
                    return cached_result
                return await expensive_operation()
            ```
        """
        return self._get_remaining_from_context()

    def get_timeout_config(
        self,
        operation: str,
    ) -> TimeoutConfig | None:
        """
        Get timeout configuration for an operation.

        Args:
            operation: Operation name

        Returns:
            TimeoutConfig or None if not registered

        Example:
            ```python
            config = manager.get_timeout_config("api_call")
            if config:
                print(f"Timeout: {config.timeout_ms}ms")
            ```
        """
        return self._configs.get(operation)

    async def get_statistics(
        self,
        security_context: SecurityContext,
        operation: str | None = None,
    ) -> dict[str, Any]:
        """
        Get timeout statistics.

        Args:
            security_context: Security context
            operation: Optional operation filter

        Returns:
            Dictionary with timeout statistics

        Example:
            ```python
            stats = await manager.get_statistics(security_context=context)
            for op, data in stats.items():
                print(f"{op}: {data['timeout_rate']:.2%} timeouts")
            ```
        """
        if operation:
            stats = self._stats.get(operation, {})
            if stats:
                total = stats["total_executions"] or 1
                return {
                    operation: {
                        **stats,
                        "timeout_rate": stats["timeouts"] / total,
                        "average_elapsed_ms": stats["total_elapsed_ms"] / total,
                    }
                }
            return {}

        result = {}
        for op, stats in self._stats.items():
            total = stats["total_executions"] or 1
            result[op] = {
                **stats,
                "timeout_rate": stats["timeouts"] / total,
                "average_elapsed_ms": stats["total_elapsed_ms"] / total,
            }

        return result

    async def reset_statistics(
        self,
        security_context: SecurityContext,
        operation: str | None = None,
    ) -> None:
        """
        Reset timeout statistics.

        Args:
            security_context: Security context
            operation: Optional operation filter

        Example:
            ```python
            await manager.reset_statistics(security_context=context)
            ```
        """
        security_context.require_permission("resilience.manage_timeout")

        if operation:
            if operation in self._stats:
                self._stats[operation] = {
                    "total_executions": 0,
                    "timeouts": 0,
                    "total_elapsed_ms": 0.0,
                    "min_elapsed_ms": float("inf"),
                    "max_elapsed_ms": 0.0,
                }
        else:
            for op in self._stats:
                self._stats[op] = {
                    "total_executions": 0,
                    "timeouts": 0,
                    "total_elapsed_ms": 0.0,
                    "min_elapsed_ms": float("inf"),
                    "max_elapsed_ms": 0.0,
                }

        logger.info(
            "Timeout statistics reset",
            extra={"operation": operation},
        )

    def _get_effective_timeout(
        self,
        operation: str,
        override: int | None = None,
    ) -> int | None:
        """
        Get effective timeout for an operation.

        Determines the timeout to use based on override, registered
        configuration, or default value. Returns None if timeout
        is disabled for the operation.

        Args:
            operation: The operation name.
            override: Optional timeout override in milliseconds.

        Returns:
            Effective timeout in milliseconds, or None if disabled.
        """
        if override is not None:
            return override

        config = self._configs.get(operation)
        if config:
            if not config.enabled:
                return None
            return config.timeout_ms

        return self.default_timeout_ms

    def _get_remaining_from_context(self) -> int | None:
        """
        Get remaining timeout from current execution context.

        Calculates the remaining time before timeout based on the
        parent operation's start time and total timeout allocation.
        Used for cascading timeout propagation to nested operations.

        Returns:
            Remaining timeout in milliseconds, or None if no context.
        """
        if self._timeout_context is None:
            return None

        start_time, total_timeout_ms = self._timeout_context
        elapsed_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
        remaining_ms = max(0, total_timeout_ms - elapsed_ms)

        return int(remaining_ms)

    async def _update_stats(
        self,
        operation: str,
        elapsed_ms: float,
        timed_out: bool,
    ) -> None:
        """
        Update execution statistics for an operation.

        Records timing metrics including total executions, timeout count,
        minimum/maximum elapsed time, and cumulative elapsed time for
        average calculations.

        Args:
            operation: The operation name.
            elapsed_ms: Elapsed execution time in milliseconds.
            timed_out: Whether the operation timed out.
        """
        async with self._lock:
            if operation not in self._stats:
                self._stats[operation] = {
                    "total_executions": 0,
                    "timeouts": 0,
                    "total_elapsed_ms": 0.0,
                    "min_elapsed_ms": float("inf"),
                    "max_elapsed_ms": 0.0,
                }

            stats = self._stats[operation]
            stats["total_executions"] += 1
            stats["total_elapsed_ms"] += elapsed_ms
            stats["min_elapsed_ms"] = min(stats["min_elapsed_ms"], elapsed_ms)
            stats["max_elapsed_ms"] = max(stats["max_elapsed_ms"], elapsed_ms)

            if timed_out:
                stats["timeouts"] += 1

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"TimeoutManager("
            f"default_timeout_ms={self.default_timeout_ms}, "
            f"registered_operations={len(self._configs)})"
        )
