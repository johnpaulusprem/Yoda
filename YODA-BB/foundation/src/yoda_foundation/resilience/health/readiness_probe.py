"""
Readiness probe for service readiness checking.

This module provides readiness probes for verifying service readiness
and dependency availability.

Example:
    ```python
    from yoda_foundation.resilience.health import (
        ReadinessProbe,
        HealthChecker,
    )

    # Create health checker and readiness probe
    health_checker = HealthChecker()
    health_checker.register_check("database", check_database, critical=True)
    health_checker.register_check("cache", check_cache, critical=False)

    readiness = ReadinessProbe(
        health_checker=health_checker,
        required_healthy_duration_ms=5000,
    )

    # Check readiness
    is_ready = await readiness.is_ready(security_context=context)
    if is_ready:
        print("Service is ready to accept traffic")
    ```
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import (
    Any,
)

from yoda_foundation.exceptions import ValidationError
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.resilience.health.health_checker import (
    HealthChecker,
    HealthCheckResult,
    HealthStatus,
)
from yoda_foundation.security.context import SecurityContext


logger = logging.getLogger(__name__)


class ReadinessStatus(Enum):
    """Readiness status values."""

    READY = "ready"
    NOT_READY = "not_ready"
    STARTING = "starting"
    STOPPING = "stopping"
    UNKNOWN = "unknown"


@dataclass
class ReadinessResult:
    """
    Result of readiness check.

    Attributes:
        status: Readiness status
        ready: Whether the service is ready
        health_result: Underlying health check result
        message: Status message
        ready_since: When the service became ready
        not_ready_reason: Reason for not being ready
        checks_passed: Number of consecutive healthy checks
        required_checks: Required consecutive healthy checks
        startup_complete: Whether startup is complete
        timestamp: When the check was performed

    Example:
        ```python
        result = await readiness.check_readiness(security_context=context)
        if result.ready:
            print(f"Ready since {result.ready_since}")
        else:
            print(f"Not ready: {result.not_ready_reason}")
        ```
    """

    status: ReadinessStatus
    ready: bool
    health_result: HealthCheckResult | None
    message: str
    ready_since: datetime | None = None
    not_ready_reason: str | None = None
    checks_passed: int = 0
    required_checks: int = 1
    startup_complete: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status.value,
            "ready": self.ready,
            "message": self.message,
            "ready_since": self.ready_since.isoformat() if self.ready_since else None,
            "not_ready_reason": self.not_ready_reason,
            "checks_passed": self.checks_passed,
            "required_checks": self.required_checks,
            "startup_complete": self.startup_complete,
            "timestamp": self.timestamp.isoformat(),
            "health": self.health_result.to_dict() if self.health_result else None,
        }


class ReadinessProbe:
    """
    Readiness probe for service readiness checking.

    Verifies service readiness by checking component health
    and tracking consecutive healthy checks.

    Attributes:
        health_checker: Health checker for component health
        required_healthy_checks: Number of consecutive healthy checks required
        required_healthy_duration_ms: Duration service must be healthy

    Example:
        ```python
        # Create readiness probe
        readiness = ReadinessProbe(
            health_checker=health_checker,
            required_healthy_checks=3,
            required_healthy_duration_ms=5000,
        )

        # Add startup checks
        readiness.add_startup_check(
            name="migrations",
            check_func=check_migrations_complete,
        )

        # Check readiness
        result = await readiness.check_readiness(security_context=context)
        if result.ready:
            start_accepting_traffic()
        else:
            wait_for_ready()

        # Simple ready check
        if await readiness.is_ready(security_context=context):
            process_request()
        ```
    """

    def __init__(
        self,
        health_checker: HealthChecker | None = None,
        required_healthy_checks: int = 1,
        required_healthy_duration_ms: int = 0,
        check_interval_ms: int = 1000,
    ) -> None:
        """
        Initialize readiness probe.

        Args:
            health_checker: Health checker for component health
            required_healthy_checks: Consecutive healthy checks required
            required_healthy_duration_ms: Duration service must be healthy
            check_interval_ms: Interval between checks

        Raises:
            ValidationError: If parameters are invalid
        """
        if required_healthy_checks < 1:
            raise ValidationError(
                message=f"required_healthy_checks must be at least 1, got {required_healthy_checks}",
                field_name="required_healthy_checks",
            )

        self.health_checker = health_checker or HealthChecker()
        self.required_healthy_checks = required_healthy_checks
        self.required_healthy_duration_ms = required_healthy_duration_ms
        self.check_interval_ms = check_interval_ms

        # State
        self._consecutive_healthy_checks = 0
        self._ready_since: datetime | None = None
        self._startup_checks: dict[str, Callable[[], Awaitable[bool]]] = {}
        self._startup_complete: dict[str, bool] = {}
        self._status = ReadinessStatus.STARTING
        self._lock = asyncio.Lock()

        # Lifecycle
        self._is_stopping = False

    def add_startup_check(
        self,
        name: str,
        check_func: Callable[[], Awaitable[bool]],
    ) -> None:
        """
        Add a startup check.

        Startup checks must pass before the service can be ready.

        Args:
            name: Check name
            check_func: Async function that returns True when complete

        Example:
            ```python
            async def check_migrations() -> bool:
                return await db.check_migrations_complete()

            readiness.add_startup_check(
                name="migrations",
                check_func=check_migrations,
            )
            ```
        """
        self._startup_checks[name] = check_func
        self._startup_complete[name] = False

        logger.debug(
            f"Added startup check: {name}",
            extra={"check_name": name},
        )

    def remove_startup_check(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> None:
        """
        Remove a startup check.

        Args:
            name: Check name
            security_context: Security context

        Example:
            ```python
            readiness.remove_startup_check(
                name="deprecated_check",
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_health")

        self._startup_checks.pop(name, None)
        self._startup_complete.pop(name, None)

    async def is_ready(
        self,
        security_context: SecurityContext,
    ) -> bool:
        """
        Check if service is ready.

        Args:
            security_context: Security context

        Returns:
            True if service is ready to accept traffic

        Example:
            ```python
            if await readiness.is_ready(security_context=context):
                process_request()
            else:
                return_service_unavailable()
            ```
        """
        result = await self.check_readiness(security_context)
        return result.ready

    async def check_readiness(
        self,
        security_context: SecurityContext,
    ) -> ReadinessResult:
        """
        Perform full readiness check.

        Args:
            security_context: Security context

        Returns:
            ReadinessResult with detailed status

        Example:
            ```python
            result = await readiness.check_readiness(security_context=context)

            if result.ready:
                print(f"Ready since {result.ready_since}")
            else:
                print(f"Not ready: {result.not_ready_reason}")
                for component in result.health_result.components:
                    if component.status != HealthStatus.HEALTHY:
                        print(f"  {component.name}: {component.error}")
            ```
        """
        # Check if stopping
        if self._is_stopping:
            return ReadinessResult(
                status=ReadinessStatus.STOPPING,
                ready=False,
                health_result=None,
                message="Service is stopping",
                not_ready_reason="Service is shutting down",
            )

        # Check startup checks
        startup_complete = await self._check_startup(security_context)
        if not startup_complete:
            incomplete = [name for name, complete in self._startup_complete.items() if not complete]
            return ReadinessResult(
                status=ReadinessStatus.STARTING,
                ready=False,
                health_result=None,
                message="Startup not complete",
                not_ready_reason=f"Waiting for: {', '.join(incomplete)}",
                startup_complete=False,
            )

        # Check health
        health_result = await self.health_checker.check_health(security_context)

        async with self._lock:
            if health_result.is_healthy or health_result.status == HealthStatus.DEGRADED:
                # Health is acceptable
                self._consecutive_healthy_checks += 1

                # Check if we have enough consecutive healthy checks
                if self._consecutive_healthy_checks >= self.required_healthy_checks:
                    if self._ready_since is None:
                        self._ready_since = datetime.now(UTC)

                    # Check duration requirement
                    if self.required_healthy_duration_ms > 0:
                        healthy_duration = (
                            datetime.now(UTC) - self._ready_since
                        ).total_seconds() * 1000

                        if healthy_duration < self.required_healthy_duration_ms:
                            remaining = self.required_healthy_duration_ms - healthy_duration
                            return ReadinessResult(
                                status=ReadinessStatus.STARTING,
                                ready=False,
                                health_result=health_result,
                                message=f"Waiting for healthy duration: {remaining:.0f}ms remaining",
                                not_ready_reason=f"Need {remaining:.0f}ms more healthy time",
                                checks_passed=self._consecutive_healthy_checks,
                                required_checks=self.required_healthy_checks,
                                startup_complete=True,
                            )

                    self._status = ReadinessStatus.READY
                    return ReadinessResult(
                        status=ReadinessStatus.READY,
                        ready=True,
                        health_result=health_result,
                        message="Service is ready",
                        ready_since=self._ready_since,
                        checks_passed=self._consecutive_healthy_checks,
                        required_checks=self.required_healthy_checks,
                        startup_complete=True,
                    )
                else:
                    # Not enough consecutive checks yet
                    remaining = self.required_healthy_checks - self._consecutive_healthy_checks
                    return ReadinessResult(
                        status=ReadinessStatus.STARTING,
                        ready=False,
                        health_result=health_result,
                        message=f"Building readiness: {remaining} more healthy checks needed",
                        not_ready_reason=f"Need {remaining} more consecutive healthy checks",
                        checks_passed=self._consecutive_healthy_checks,
                        required_checks=self.required_healthy_checks,
                        startup_complete=True,
                    )

            else:
                # Health check failed
                self._consecutive_healthy_checks = 0
                self._ready_since = None
                self._status = ReadinessStatus.NOT_READY

                # Find unhealthy components
                unhealthy = [
                    c.name for c in health_result.components if c.status == HealthStatus.UNHEALTHY
                ]

                return ReadinessResult(
                    status=ReadinessStatus.NOT_READY,
                    ready=False,
                    health_result=health_result,
                    message="Health check failed",
                    not_ready_reason=f"Unhealthy components: {', '.join(unhealthy)}",
                    checks_passed=0,
                    required_checks=self.required_healthy_checks,
                    startup_complete=True,
                )

    async def _check_startup(
        self,
        security_context: SecurityContext,
    ) -> bool:
        """Check all startup checks."""
        if not self._startup_checks:
            return True

        all_complete = True

        for name, check_func in self._startup_checks.items():
            if self._startup_complete.get(name):
                continue

            try:
                is_complete = await check_func()
                if is_complete:
                    self._startup_complete[name] = True
                    logger.info(
                        f"Startup check '{name}' completed",
                        extra={"check_name": name},
                    )
                else:
                    all_complete = False

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
                logger.warning(
                    f"Startup check '{name}' failed: {e}",
                    extra={"check_name": name, "error": str(e)},
                )
                all_complete = False

        return all_complete

    async def mark_stopping(
        self,
        security_context: SecurityContext,
    ) -> None:
        """
        Mark service as stopping.

        Call this during graceful shutdown to indicate the service
        should no longer accept traffic.

        Args:
            security_context: Security context

        Example:
            ```python
            async def shutdown():
                await readiness.mark_stopping(security_context=context)
                await drain_connections()
                await cleanup()
            ```
        """
        security_context.require_permission("resilience.manage_health")

        async with self._lock:
            self._is_stopping = True
            self._status = ReadinessStatus.STOPPING

        logger.info("Service marked as stopping")

    async def mark_started(
        self,
        security_context: SecurityContext,
    ) -> None:
        """
        Mark service as started (reset stopping state).

        Args:
            security_context: Security context

        Example:
            ```python
            # Reset after failed shutdown
            await readiness.mark_started(security_context=context)
            ```
        """
        security_context.require_permission("resilience.manage_health")

        async with self._lock:
            self._is_stopping = False
            self._status = ReadinessStatus.STARTING

        logger.info("Service marked as started")

    async def reset(
        self,
        security_context: SecurityContext,
    ) -> None:
        """
        Reset readiness state.

        Args:
            security_context: Security context

        Example:
            ```python
            await readiness.reset(security_context=context)
            ```
        """
        security_context.require_permission("resilience.manage_health")

        async with self._lock:
            self._consecutive_healthy_checks = 0
            self._ready_since = None
            self._is_stopping = False
            self._status = ReadinessStatus.STARTING

            for name in self._startup_complete:
                self._startup_complete[name] = False

        logger.info("Readiness probe reset")

    async def wait_for_ready(
        self,
        security_context: SecurityContext,
        timeout_ms: int = 60000,
        poll_interval_ms: int = 1000,
    ) -> bool:
        """
        Wait for service to become ready.

        Args:
            security_context: Security context
            timeout_ms: Maximum time to wait
            poll_interval_ms: Interval between checks

        Returns:
            True if service became ready, False on timeout

        Example:
            ```python
            if await readiness.wait_for_ready(
                security_context=context,
                timeout_ms=30000,
            ):
                print("Service ready!")
            else:
                print("Timeout waiting for readiness")
            ```
        """
        start_time = datetime.now(UTC)
        timeout_seconds = timeout_ms / 1000.0

        while True:
            if await self.is_ready(security_context):
                return True

            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            if elapsed >= timeout_seconds:
                return False

            await asyncio.sleep(poll_interval_ms / 1000.0)

    async def get_status(
        self,
        security_context: SecurityContext,
    ) -> dict[str, Any]:
        """
        Get current readiness status summary.

        Args:
            security_context: Security context

        Returns:
            Dictionary with status summary

        Example:
            ```python
            status = await readiness.get_status(security_context=context)
            print(f"Status: {status['status']}")
            print(f"Consecutive healthy: {status['consecutive_healthy_checks']}")
            ```
        """
        async with self._lock:
            return {
                "status": self._status.value,
                "consecutive_healthy_checks": self._consecutive_healthy_checks,
                "required_healthy_checks": self.required_healthy_checks,
                "ready_since": self._ready_since.isoformat() if self._ready_since else None,
                "is_stopping": self._is_stopping,
                "startup_complete": dict(self._startup_complete),
            }

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"ReadinessProbe("
            f"status={self._status.value}, "
            f"consecutive_healthy={self._consecutive_healthy_checks}, "
            f"required={self.required_healthy_checks})"
        )
