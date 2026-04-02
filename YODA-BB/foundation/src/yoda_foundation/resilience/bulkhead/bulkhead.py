"""
Bulkhead pattern for resource isolation.

This module provides the base bulkhead implementation for isolating resources
and preventing cascading failures.

Example:
    ```python
    from yoda_foundation.resilience.bulkhead import Bulkhead

    # Create bulkhead
    bulkhead = Bulkhead(
        name="external_api",
        max_concurrent=10,
    )

    # Execute with isolation
    result = await bulkhead.execute(
        func=api_call,
        security_context=context,
    )

    # Check statistics
    stats = await bulkhead.get_statistics(security_context=context)
    print(f"Active: {stats.active_count}/{stats.max_concurrent}")
    ```
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import (
    Any,
    TypeVar,
)

from yoda_foundation.exceptions import (
    ResilienceError,
    ValidationError,
)
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.security.context import SecurityContext


T = TypeVar("T")

logger = logging.getLogger(__name__)


class BulkheadRejectionReason(Enum):
    """Reasons for bulkhead rejection."""

    MAX_CONCURRENT_REACHED = "max_concurrent_reached"
    QUEUE_FULL = "queue_full"
    TIMEOUT = "timeout"
    DISABLED = "disabled"


class BulkheadRejectedException(ResilienceError):
    """
    Exception raised when a request is rejected by the bulkhead.

    Attributes:
        bulkhead_name: Name of the bulkhead
        rejection_reason: Reason for rejection
        current_active: Current number of active requests
        max_concurrent: Maximum concurrent requests allowed

    Example:
        ```python
        try:
            await bulkhead.execute(func=api_call, security_context=context)
        except BulkheadRejectedException as e:
            logger.warning(f"Rejected by {e.bulkhead_name}: {e.rejection_reason}")
        ```
    """

    def __init__(
        self,
        bulkhead_name: str,
        rejection_reason: BulkheadRejectionReason,
        current_active: int,
        max_concurrent: int,
        queue_size: int | None = None,
        max_queue_size: int | None = None,
    ) -> None:
        """
        Initialize bulkhead rejected exception.

        Args:
            bulkhead_name: Name of the bulkhead
            rejection_reason: Reason for rejection
            current_active: Current number of active requests
            max_concurrent: Maximum concurrent requests allowed
            queue_size: Current queue size
            max_queue_size: Maximum queue size
        """
        self.bulkhead_name = bulkhead_name
        self.rejection_reason = rejection_reason
        self.current_active = current_active
        self.max_concurrent = max_concurrent
        self.queue_size = queue_size
        self.max_queue_size = max_queue_size

        message = (
            f"Bulkhead '{bulkhead_name}' rejected request: {rejection_reason.value}. "
            f"Active: {current_active}/{max_concurrent}"
        )
        if queue_size is not None and max_queue_size is not None:
            message += f", Queue: {queue_size}/{max_queue_size}"

        super().__init__(
            message=message,
            operation="bulkhead_acquire",
            component="bulkhead",
            suggestions=[
                "Wait and retry later",
                "Reduce concurrent requests",
                "Increase bulkhead limits if appropriate",
            ],
            details={
                "bulkhead_name": bulkhead_name,
                "rejection_reason": rejection_reason.value,
                "current_active": current_active,
                "max_concurrent": max_concurrent,
                "queue_size": queue_size,
                "max_queue_size": max_queue_size,
            },
        )


@dataclass
class BulkheadConfig:
    """
    Configuration for bulkhead.

    Attributes:
        name: Bulkhead name
        max_concurrent: Maximum concurrent requests
        max_queue_size: Maximum queue size (0 = no queue)
        queue_timeout_ms: Timeout for queued requests
        enabled: Whether the bulkhead is enabled
        metrics_enabled: Whether to collect metrics

    Example:
        ```python
        config = BulkheadConfig(
            name="api_bulkhead",
            max_concurrent=10,
            max_queue_size=50,
            queue_timeout_ms=5000,
        )
        ```
    """

    name: str
    max_concurrent: int = 10
    max_queue_size: int = 0
    queue_timeout_ms: int = 30000
    enabled: bool = True
    metrics_enabled: bool = True


@dataclass
class BulkheadStatistics:
    """
    Bulkhead statistics.

    Attributes:
        name: Bulkhead name
        max_concurrent: Maximum concurrent limit
        active_count: Currently active requests
        queue_size: Current queue size
        max_queue_size: Maximum queue size
        total_requests: Total requests received
        successful_requests: Successfully completed requests
        rejected_requests: Rejected requests
        timed_out_requests: Timed out requests
        average_wait_time_ms: Average queue wait time

    Example:
        ```python
        stats = await bulkhead.get_statistics(security_context=context)
        print(f"Active: {stats.active_count}/{stats.max_concurrent}")
        print(f"Rejection rate: {stats.rejection_rate:.2%}")
        ```
    """

    name: str
    max_concurrent: int
    active_count: int
    queue_size: int
    max_queue_size: int
    total_requests: int
    successful_requests: int
    rejected_requests: int
    timed_out_requests: int
    average_wait_time_ms: float

    @property
    def rejection_rate(self) -> float:
        """Calculate rejection rate."""
        if self.total_requests == 0:
            return 0.0
        return self.rejected_requests / self.total_requests

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests

    @property
    def utilization(self) -> float:
        """Calculate current utilization."""
        if self.max_concurrent == 0:
            return 0.0
        return self.active_count / self.max_concurrent


class Bulkhead(ABC):
    """
    Base bulkhead for resource isolation.

    Implements the bulkhead pattern to isolate resources and prevent
    cascading failures through resource exhaustion.

    Attributes:
        config: Bulkhead configuration

    Example:
        ```python
        bulkhead = SemaphoreBulkhead(
            name="api_calls",
            max_concurrent=10,
            max_queue_size=50,
        )

        # Use context manager
        async with bulkhead.acquire(security_context=context):
            result = await api_call()

        # Or use execute method
        result = await bulkhead.execute(
            func=api_call,
            security_context=context,
        )
        ```
    """

    def __init__(self, config: BulkheadConfig) -> None:
        """
        Initialize bulkhead.

        Args:
            config: Bulkhead configuration

        Raises:
            ValidationError: If configuration is invalid
        """
        if config.max_concurrent < 1:
            raise ValidationError(
                message=f"max_concurrent must be at least 1, got {config.max_concurrent}",
                field_name="max_concurrent",
            )

        if config.max_queue_size < 0:
            raise ValidationError(
                message=f"max_queue_size cannot be negative, got {config.max_queue_size}",
                field_name="max_queue_size",
            )

        self.config = config

        # Statistics
        self._total_requests = 0
        self._successful_requests = 0
        self._rejected_requests = 0
        self._timed_out_requests = 0
        self._total_wait_time_ms: float = 0.0
        self._wait_count = 0
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        """Get bulkhead name."""
        return self.config.name

    @property
    def max_concurrent(self) -> int:
        """Get maximum concurrent limit."""
        return self.config.max_concurrent

    @abstractmethod
    async def _acquire_internal(
        self,
        timeout_ms: int | None = None,
    ) -> bool:
        """
        Internal method to acquire bulkhead permit.

        Args:
            timeout_ms: Timeout in milliseconds

        Returns:
            True if permit acquired, False otherwise
        """
        pass

    @abstractmethod
    async def _release_internal(self) -> None:
        """Internal method to release bulkhead permit."""
        pass

    @abstractmethod
    async def _get_active_count(self) -> int:
        """Get current number of active requests."""
        pass

    @abstractmethod
    async def _get_queue_size(self) -> int:
        """Get current queue size."""
        pass

    @asynccontextmanager
    async def acquire(
        self,
        security_context: SecurityContext,
        timeout_ms: int | None = None,
    ) -> AsyncIterator[None]:
        """
        Acquire bulkhead permit as context manager.

        Args:
            security_context: Security context
            timeout_ms: Optional timeout override

        Yields:
            None when permit is acquired

        Raises:
            BulkheadRejectedException: If request is rejected

        Example:
            ```python
            async with bulkhead.acquire(security_context=context):
                result = await protected_operation()
            ```
        """
        if not self.config.enabled:
            # Bulkhead disabled, pass through
            yield
            return

        async with self._lock:
            self._total_requests += 1

        effective_timeout = timeout_ms or self.config.queue_timeout_ms
        start_time = datetime.now(UTC)

        try:
            acquired = await self._acquire_internal(timeout_ms=effective_timeout)

            if not acquired:
                async with self._lock:
                    self._rejected_requests += 1

                active = await self._get_active_count()
                queue_size = await self._get_queue_size()

                raise BulkheadRejectedException(
                    bulkhead_name=self.config.name,
                    rejection_reason=BulkheadRejectionReason.TIMEOUT,
                    current_active=active,
                    max_concurrent=self.config.max_concurrent,
                    queue_size=queue_size,
                    max_queue_size=self.config.max_queue_size,
                )

            # Track wait time
            wait_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
            async with self._lock:
                self._total_wait_time_ms += wait_time
                self._wait_count += 1

            yield

            async with self._lock:
                self._successful_requests += 1

        except BulkheadRejectedException:
            raise
        except (
            AgenticBaseException,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
        ):
            raise
        finally:
            await self._release_internal()

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        security_context: SecurityContext,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> T:
        """
        Execute function with bulkhead protection.

        Args:
            func: Async function to execute
            security_context: Security context
            args: Positional arguments
            kwargs: Keyword arguments
            timeout_ms: Optional timeout override

        Returns:
            Function result

        Raises:
            BulkheadRejectedException: If request is rejected
            Exception: If function raises exception

        Example:
            ```python
            result = await bulkhead.execute(
                func=api_call,
                args=(endpoint,),
                kwargs={"params": params},
                security_context=context,
            )
            ```
        """
        kwargs = kwargs or {}

        async with self.acquire(security_context=security_context, timeout_ms=timeout_ms):
            return await func(*args, **kwargs)

    async def release(
        self,
        security_context: SecurityContext,
    ) -> None:
        """
        Manually release bulkhead permit.

        Note: Prefer using context manager or execute method.

        Args:
            security_context: Security context

        Example:
            ```python
            # Manual acquire/release (not recommended)
            acquired = await bulkhead.try_acquire(security_context=context)
            if acquired:
                try:
                    await protected_operation()
                finally:
                    await bulkhead.release(security_context=context)
            ```
        """
        await self._release_internal()

    async def get_statistics(
        self,
        security_context: SecurityContext,
    ) -> BulkheadStatistics:
        """
        Get bulkhead statistics.

        Args:
            security_context: Security context

        Returns:
            BulkheadStatistics with current state and metrics

        Example:
            ```python
            stats = await bulkhead.get_statistics(security_context=context)
            print(f"Utilization: {stats.utilization:.2%}")
            print(f"Rejection rate: {stats.rejection_rate:.2%}")
            ```
        """
        async with self._lock:
            avg_wait = self._total_wait_time_ms / self._wait_count if self._wait_count > 0 else 0.0

            return BulkheadStatistics(
                name=self.config.name,
                max_concurrent=self.config.max_concurrent,
                active_count=await self._get_active_count(),
                queue_size=await self._get_queue_size(),
                max_queue_size=self.config.max_queue_size,
                total_requests=self._total_requests,
                successful_requests=self._successful_requests,
                rejected_requests=self._rejected_requests,
                timed_out_requests=self._timed_out_requests,
                average_wait_time_ms=avg_wait,
            )

    async def reset_statistics(
        self,
        security_context: SecurityContext,
    ) -> None:
        """
        Reset bulkhead statistics.

        Args:
            security_context: Security context

        Example:
            ```python
            await bulkhead.reset_statistics(security_context=context)
            ```
        """
        security_context.require_permission("resilience.manage_bulkhead")

        async with self._lock:
            self._total_requests = 0
            self._successful_requests = 0
            self._rejected_requests = 0
            self._timed_out_requests = 0
            self._total_wait_time_ms = 0.0
            self._wait_count = 0

        logger.info(
            f"Bulkhead '{self.config.name}' statistics reset",
            extra={"bulkhead_name": self.config.name},
        )

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"Bulkhead("
            f"name={self.config.name}, "
            f"max_concurrent={self.config.max_concurrent}, "
            f"enabled={self.config.enabled})"
        )
