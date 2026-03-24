"""
Retry budget management for preventing retry storms.

This module provides retry budgets to limit total retries across
all operations within a time window, preventing resource exhaustion.

Example:
    ```python
    from yoda_foundation.resilience.retry import RetryBudget
    from yoda_foundation.security import create_security_context

    # Create retry budget: max 100 retries per minute
    budget = RetryBudget(
        max_retries=100,
        time_window_seconds=60,
    )

    # Check if retry is allowed
    context = create_security_context(user_id="user_123")
    if await budget.can_retry(security_context=context):
        # Consume budget
        await budget.consume(security_context=context)
        # Perform retry
        ...
    else:
        # Budget exhausted
        raise RetryBudgetExceededError(...)
    ```
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from yoda_foundation.exceptions import (
    RetryBudgetExceededError,
    ValidationError,
)
from yoda_foundation.security.context import SecurityContext


@dataclass
class RetryBudget:
    """
    Retry budget to prevent retry storms.

    Limits total number of retries within a time window to prevent
    resource exhaustion and cascading failures.

    Attributes:
        max_retries: Maximum retries allowed in time window
        time_window_seconds: Time window in seconds
        scope: Budget scope ("global", "user", "tenant")
        reset_on_success: Whether to reset budget on successful operation

    Example:
        ```python
        # Global budget: max 1000 retries per 5 minutes
        budget = RetryBudget(
            max_retries=1000,
            time_window_seconds=300,
            scope="global",
        )

        # Per-user budget: max 50 retries per minute
        budget = RetryBudget(
            max_retries=50,
            time_window_seconds=60,
            scope="user",
        )
        ```
    """

    max_retries: int = 100
    time_window_seconds: int = 60
    scope: str = "global"
    reset_on_success: bool = False

    # Internal state (not part of constructor)
    _retry_timestamps: dict[str, deque[datetime]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate budget configuration."""
        if self.max_retries <= 0:
            raise ValidationError(
                message=f"max_retries must be positive, got {self.max_retries}",
                field_name="max_retries",
            )

        if self.time_window_seconds <= 0:
            raise ValidationError(
                message=f"time_window_seconds must be positive, got {self.time_window_seconds}",
                field_name="time_window_seconds",
            )

        if self.scope not in ("global", "user", "tenant"):
            raise ValidationError(
                message=f"scope must be 'global', 'user', or 'tenant', got {self.scope}",
                field_name="scope",
            )

    async def can_retry(
        self,
        security_context: SecurityContext,
    ) -> bool:
        """
        Check if retry is allowed within budget.

        Args:
            security_context: Security context for scoping

        Returns:
            True if retry is allowed

        Example:
            ```python
            if await budget.can_retry(security_context=context):
                # Retry allowed
                await retry_operation()
            else:
                # Budget exceeded
                raise RetryBudgetExceededError(...)
            ```
        """
        async with self._lock:
            scope_key = self._get_scope_key(security_context)
            self._cleanup_old_retries(scope_key)

            retry_count = self._get_retry_count(scope_key)
            return retry_count < self.max_retries

    async def consume(
        self,
        security_context: SecurityContext,
        count: int = 1,
    ) -> None:
        """
        Consume retry budget.

        Args:
            security_context: Security context for scoping
            count: Number of retries to consume (default 1)

        Raises:
            RetryBudgetExceededError: If budget is exceeded

        Example:
            ```python
            # Check and consume in one call
            await budget.consume(security_context=context)

            # Consume multiple retries
            await budget.consume(security_context=context, count=3)
            ```
        """
        async with self._lock:
            scope_key = self._get_scope_key(security_context)
            self._cleanup_old_retries(scope_key)

            current_count = self._get_retry_count(scope_key)
            if current_count + count > self.max_retries:
                raise RetryBudgetExceededError(
                    current_retries=current_count,
                    budget_limit=self.max_retries,
                    time_window=f"{self.time_window_seconds} seconds",
                )

            # Record retry timestamps
            if scope_key not in self._retry_timestamps:
                self._retry_timestamps[scope_key] = deque()

            now = datetime.now(UTC)
            for _ in range(count):
                self._retry_timestamps[scope_key].append(now)

    async def reset(
        self,
        security_context: SecurityContext,
    ) -> None:
        """
        Reset retry budget for scope.

        Args:
            security_context: Security context for scoping

        Example:
            ```python
            # Reset budget after successful operation
            await budget.reset(security_context=context)
            ```
        """
        if not self.reset_on_success:
            return

        async with self._lock:
            scope_key = self._get_scope_key(security_context)
            if scope_key in self._retry_timestamps:
                self._retry_timestamps[scope_key].clear()

    async def get_remaining(
        self,
        security_context: SecurityContext,
    ) -> int:
        """
        Get remaining retry budget.

        Args:
            security_context: Security context for scoping

        Returns:
            Number of retries remaining

        Example:
            ```python
            remaining = await budget.get_remaining(security_context=context)
            print(f"Retries remaining: {remaining}/{budget.max_retries}")
            ```
        """
        async with self._lock:
            scope_key = self._get_scope_key(security_context)
            self._cleanup_old_retries(scope_key)

            current_count = self._get_retry_count(scope_key)
            return max(0, self.max_retries - current_count)

    async def get_statistics(
        self,
        security_context: SecurityContext,
    ) -> dict[str, any]:
        """
        Get retry budget statistics.

        Args:
            security_context: Security context for scoping

        Returns:
            Dictionary with budget statistics

        Example:
            ```python
            stats = await budget.get_statistics(security_context=context)
            print(f"Used: {stats['used']}")
            print(f"Remaining: {stats['remaining']}")
            print(f"Utilization: {stats['utilization_percentage']}%")
            ```
        """
        async with self._lock:
            scope_key = self._get_scope_key(security_context)
            self._cleanup_old_retries(scope_key)

            used = self._get_retry_count(scope_key)
            remaining = max(0, self.max_retries - used)
            utilization = (used / self.max_retries * 100) if self.max_retries > 0 else 0

            return {
                "max_retries": self.max_retries,
                "time_window_seconds": self.time_window_seconds,
                "scope": self.scope,
                "used": used,
                "remaining": remaining,
                "utilization_percentage": round(utilization, 2),
                "scope_key": scope_key,
            }

    def _get_scope_key(self, security_context: SecurityContext) -> str:
        """
        Get scope key for budget tracking.

        Args:
            security_context: Security context

        Returns:
            Scope key string
        """
        if self.scope == "global":
            return "global"
        elif self.scope == "user":
            return f"user:{security_context.user_id}"
        else:  # tenant
            return f"tenant:{security_context.tenant_id or 'default'}"

    def _cleanup_old_retries(self, scope_key: str) -> None:
        """
        Remove retry timestamps outside time window.

        Args:
            scope_key: Scope key
        """
        if scope_key not in self._retry_timestamps:
            return

        cutoff_time = datetime.now(UTC) - timedelta(seconds=self.time_window_seconds)

        # Remove old timestamps
        timestamps = self._retry_timestamps[scope_key]
        while timestamps and timestamps[0] < cutoff_time:
            timestamps.popleft()

    def _get_retry_count(self, scope_key: str) -> int:
        """
        Get current retry count for scope.

        Args:
            scope_key: Scope key

        Returns:
            Number of retries in current window
        """
        if scope_key not in self._retry_timestamps:
            return 0

        return len(self._retry_timestamps[scope_key])

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"RetryBudget("
            f"max={self.max_retries}, "
            f"window={self.time_window_seconds}s, "
            f"scope={self.scope})"
        )
