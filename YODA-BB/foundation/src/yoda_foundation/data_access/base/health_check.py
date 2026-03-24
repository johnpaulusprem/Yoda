"""
Health check framework for the Agentic AI Component Library Data Access layer.

This module provides standardized health checking for database connectors
and other data access components with status tracking and reporting.

Example:
    ```python
    from yoda_foundation.data_access.base import (
        HealthStatus,
        HealthCheckResult,
        HealthChecker,
    )
    from yoda_foundation.security import create_security_context

    # Create health checker
    checker = HealthChecker(name="database_cluster")

    # Register checks
    async def check_postgres(ctx):
        return await postgres_pool.check_connection()

    async def check_redis(ctx):
        return await redis_client.ping()

    checker.register_check("postgres", check_postgres)
    checker.register_check("redis", check_redis)

    # Run health check
    context = create_security_context(
        user_id="health_monitor",
        permissions=["health.check"],
    )
    result = await checker.check(context)

    if result.status == HealthStatus.UNHEALTHY:
        alert_ops_team(result)
    ```
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from yoda_foundation.exceptions import (
    AuthorizationError,
    ValidationError,
)
from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)
from yoda_foundation.security.context import SecurityContext


class HealthStatus(Enum):
    """
    Health status enumeration for services and components.

    Attributes:
        HEALTHY: Service is operating normally
        DEGRADED: Service is operational but with reduced capacity or performance
        UNHEALTHY: Service is not operational or has critical issues
        UNKNOWN: Health status cannot be determined
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

    def __lt__(self, other: HealthStatus) -> bool:
        """Compare status severity (UNHEALTHY < DEGRADED < HEALTHY < UNKNOWN)."""
        order = {
            HealthStatus.UNHEALTHY: 0,
            HealthStatus.DEGRADED: 1,
            HealthStatus.HEALTHY: 2,
            HealthStatus.UNKNOWN: 3,
        }
        if isinstance(other, HealthStatus):
            return order[self] < order[other]
        return NotImplemented

    @property
    def is_operational(self) -> bool:
        """Check if status indicates service is operational."""
        return self in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)


class HealthCheckError(AgenticBaseException):
    """
    Exception raised when a health check fails.

    Attributes:
        check_name: Name of the health check that failed
        component: Component being checked

    Example:
        ```python
        raise HealthCheckError(
            message="Database connection check failed",
            check_name="postgres_connection",
            component="database",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Health check failed",
        *,
        check_name: str | None = None,
        component: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize health check error.

        Args:
            message: Human-readable error description
            check_name: Name of the health check
            component: Component being checked
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.check_name = check_name
        self.component = component

        extra_details = {
            "check_name": check_name,
            "component": component,
        }

        merged_details = {**extra_details, **(details or {})}

        super().__init__(
            message=message,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.HIGH,
            retryable=True,
            user_message="Service health check failed.",
            suggestions=suggestions
            or [
                "Check service connectivity",
                "Verify service is running",
                "Review service logs for errors",
            ],
            cause=cause,
            details=merged_details,
        )


@dataclass
class HealthCheckResult:
    """
    Result of a health check operation.

    Contains the status, timing, and detailed information about
    a health check execution.

    Attributes:
        status: Overall health status
        latency_ms: Time taken for health check in milliseconds
        details: Additional check-specific details
        timestamp: When the check was performed
        error: Error message if check failed
        check_name: Name of the check (if part of a composite check)
        component: Component that was checked

    Example:
        ```python
        result = HealthCheckResult(
            status=HealthStatus.HEALTHY,
            latency_ms=15.3,
            details={
                "connections_active": 5,
                "connections_available": 15,
                "version": "PostgreSQL 15.1",
            },
        )

        if result.is_healthy:
            print(f"Service healthy, latency: {result.latency_ms}ms")
        ```
    """

    status: HealthStatus
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None
    check_name: str | None = None
    component: str | None = None

    @property
    def is_healthy(self) -> bool:
        """
        Check if status is HEALTHY.

        Returns:
            True if status is HEALTHY
        """
        return self.status == HealthStatus.HEALTHY

    @property
    def is_operational(self) -> bool:
        """
        Check if service is operational (HEALTHY or DEGRADED).

        Returns:
            True if service can handle requests
        """
        return self.status.is_operational

    def to_dict(self) -> dict[str, Any]:
        """
        Convert result to dictionary for API response.

        Returns:
            Dictionary representation

        Example:
            ```python
            result_dict = result.to_dict()
            return JSONResponse(content=result_dict)
            ```
        """
        return {
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
            "check_name": self.check_name,
            "component": self.component,
        }

    def to_log_dict(self) -> dict[str, Any]:
        """
        Convert result to dictionary for logging.

        Returns:
            Dictionary suitable for structured logging
        """
        return {
            "health_status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "check_name": self.check_name,
            "component": self.component,
            "is_healthy": self.is_healthy,
            "error": self.error,
        }

    @classmethod
    def healthy(
        cls,
        latency_ms: float = 0.0,
        details: dict[str, Any] | None = None,
        check_name: str | None = None,
        component: str | None = None,
    ) -> HealthCheckResult:
        """
        Create a healthy result.

        Args:
            latency_ms: Check latency
            details: Additional details
            check_name: Name of the check
            component: Component checked

        Returns:
            Healthy HealthCheckResult

        Example:
            ```python
            return HealthCheckResult.healthy(
                latency_ms=5.2,
                details={"pool_size": 10},
            )
            ```
        """
        return cls(
            status=HealthStatus.HEALTHY,
            latency_ms=latency_ms,
            details=details or {},
            check_name=check_name,
            component=component,
        )

    @classmethod
    def degraded(
        cls,
        reason: str,
        latency_ms: float = 0.0,
        details: dict[str, Any] | None = None,
        check_name: str | None = None,
        component: str | None = None,
    ) -> HealthCheckResult:
        """
        Create a degraded result.

        Args:
            reason: Reason for degraded status
            latency_ms: Check latency
            details: Additional details
            check_name: Name of the check
            component: Component checked

        Returns:
            Degraded HealthCheckResult

        Example:
            ```python
            return HealthCheckResult.degraded(
                reason="High connection pool utilization",
                latency_ms=150.0,
                details={"pool_utilization": 0.85},
            )
            ```
        """
        return cls(
            status=HealthStatus.DEGRADED,
            latency_ms=latency_ms,
            details=details or {},
            error=reason,
            check_name=check_name,
            component=component,
        )

    @classmethod
    def unhealthy(
        cls,
        error: str,
        latency_ms: float = 0.0,
        details: dict[str, Any] | None = None,
        check_name: str | None = None,
        component: str | None = None,
    ) -> HealthCheckResult:
        """
        Create an unhealthy result.

        Args:
            error: Error description
            latency_ms: Check latency
            details: Additional details
            check_name: Name of the check
            component: Component checked

        Returns:
            Unhealthy HealthCheckResult

        Example:
            ```python
            return HealthCheckResult.unhealthy(
                error="Connection refused",
                details={"host": "db.example.com", "port": 5432},
            )
            ```
        """
        return cls(
            status=HealthStatus.UNHEALTHY,
            latency_ms=latency_ms,
            details=details or {},
            error=error,
            check_name=check_name,
            component=component,
        )

    @classmethod
    def unknown(
        cls,
        reason: str = "Unable to determine health status",
        check_name: str | None = None,
        component: str | None = None,
    ) -> HealthCheckResult:
        """
        Create an unknown status result.

        Args:
            reason: Reason status is unknown
            check_name: Name of the check
            component: Component checked

        Returns:
            Unknown HealthCheckResult

        Example:
            ```python
            return HealthCheckResult.unknown(
                reason="Health check not configured",
            )
            ```
        """
        return cls(
            status=HealthStatus.UNKNOWN,
            latency_ms=0.0,
            error=reason,
            check_name=check_name,
            component=component,
        )


# Type alias for health check functions
HealthCheckFn = Callable[
    [SecurityContext],
    Coroutine[Any, Any, HealthCheckResult],
]


class HealthChecker:
    """
    Composite health checker that manages multiple health checks.

    Provides registration, execution, and aggregation of health checks
    for data access components.

    Attributes:
        name: Name of this health checker
        timeout_seconds: Default timeout for health checks
        checks: Registered health check functions

    Example:
        ```python
        # Create checker
        checker = HealthChecker(
            name="data_layer",
            timeout_seconds=5.0,
        )

        # Register checks
        checker.register_check("postgres", check_postgres)
        checker.register_check("redis", check_redis)
        checker.register_check("elasticsearch", check_es)

        # Run all checks
        result = await checker.check(security_context)

        # Get aggregate status
        if result.status == HealthStatus.UNHEALTHY:
            logger.error(
                "Data layer unhealthy",
                extra=result.to_log_dict(),
            )
        ```
    """

    # Permission constant
    PERMISSION_CHECK = "health.check"

    def __init__(
        self,
        name: str = "default",
        timeout_seconds: float = 10.0,
    ) -> None:
        """
        Initialize health checker.

        Args:
            name: Name for this health checker
            timeout_seconds: Default timeout for individual checks
        """
        self._name = name
        self._timeout_seconds = timeout_seconds
        self._checks: dict[str, HealthCheckFn] = {}
        self._last_result: HealthCheckResult | None = None
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        """Return health checker name."""
        return self._name

    @property
    def timeout_seconds(self) -> float:
        """Return default timeout in seconds."""
        return self._timeout_seconds

    @property
    def check_names(self) -> list[str]:
        """Return list of registered check names."""
        return list(self._checks.keys())

    def register_check(
        self,
        name: str,
        check_fn: HealthCheckFn,
    ) -> None:
        """
        Register a health check function.

        Args:
            name: Unique name for this check
            check_fn: Async function that returns HealthCheckResult

        Raises:
            ValidationError: If check name is invalid or already registered

        Example:
            ```python
            async def check_database(ctx: SecurityContext) -> HealthCheckResult:
                try:
                    await pool.execute("SELECT 1")
                    return HealthCheckResult.healthy()
                except (ConnectionError, TimeoutError, OSError) as e:
                    return HealthCheckResult.unhealthy(str(e))

            checker.register_check("database", check_database)
            ```
        """
        if not name:
            raise ValidationError(
                message="Check name cannot be empty",
                suggestions=["Provide a non-empty check name"],
            )

        if name in self._checks:
            raise ValidationError(
                message=f"Check '{name}' is already registered",
                suggestions=[f"Use a different name or unregister '{name}' first"],
            )

        self._checks[name] = check_fn

    def unregister_check(self, name: str) -> bool:
        """
        Unregister a health check.

        Args:
            name: Name of the check to remove

        Returns:
            True if check was removed, False if not found

        Example:
            ```python
            if checker.unregister_check("old_database"):
                print("Check removed")
            ```
        """
        if name in self._checks:
            del self._checks[name]
            return True
        return False

    async def check(
        self,
        security_context: SecurityContext,
        *,
        timeout_seconds: float | None = None,
        fail_fast: bool = False,
    ) -> HealthCheckResult:
        """
        Execute all registered health checks.

        Args:
            security_context: Security context with health.check permission
            timeout_seconds: Override default timeout
            fail_fast: Stop on first unhealthy check

        Returns:
            Aggregate HealthCheckResult

        Raises:
            AuthorizationError: If user lacks health.check permission

        Example:
            ```python
            result = await checker.check(context)

            if result.is_healthy:
                print("All systems operational")
            elif result.status == HealthStatus.DEGRADED:
                print(f"Degraded: {result.error}")
            else:
                print(f"Unhealthy: {result.error}")
                for name, check_result in result.details.get("checks", {}).items():
                    if check_result["status"] == "unhealthy":
                        print(f"  - {name}: {check_result['error']}")
            ```
        """
        # Check permission
        if not security_context.has_permission(self.PERMISSION_CHECK):
            raise AuthorizationError(
                message=f"Permission denied: {self.PERMISSION_CHECK}",
                required_permission=self.PERMISSION_CHECK,
                resource=f"health_checker:{self._name}",
                user_id=security_context.user_id,
            )

        # Handle empty checker
        if not self._checks:
            return HealthCheckResult.unknown(
                reason="No health checks registered",
                check_name=self._name,
            )

        timeout = timeout_seconds or self._timeout_seconds
        start_time = time.perf_counter()

        # Execute all checks
        check_results: dict[str, HealthCheckResult] = {}
        errors: list[str] = []

        if fail_fast:
            # Sequential execution with early exit
            for name, check_fn in self._checks.items():
                result = await self._run_single_check(name, check_fn, security_context, timeout)
                check_results[name] = result

                if result.status == HealthStatus.UNHEALTHY:
                    break
        else:
            # Parallel execution of all checks
            tasks = {
                name: self._run_single_check(name, check_fn, security_context, timeout)
                for name, check_fn in self._checks.items()
            }

            results = await asyncio.gather(*tasks.values(), return_exceptions=True)

            for name, result in zip(tasks.keys(), results):
                if isinstance(result, Exception):
                    check_results[name] = HealthCheckResult.unhealthy(
                        error=str(result),
                        check_name=name,
                    )
                else:
                    check_results[name] = result

        # Calculate aggregate status
        aggregate_status = self._aggregate_status(check_results)

        # Collect errors
        for name, result in check_results.items():
            if result.error and result.status != HealthStatus.HEALTHY:
                errors.append(f"{name}: {result.error}")

        total_latency = (time.perf_counter() - start_time) * 1000

        # Build details
        details: dict[str, Any] = {
            "checks": {name: result.to_dict() for name, result in check_results.items()},
            "healthy_count": sum(
                1 for r in check_results.values() if r.status == HealthStatus.HEALTHY
            ),
            "degraded_count": sum(
                1 for r in check_results.values() if r.status == HealthStatus.DEGRADED
            ),
            "unhealthy_count": sum(
                1 for r in check_results.values() if r.status == HealthStatus.UNHEALTHY
            ),
            "total_checks": len(check_results),
        }

        result = HealthCheckResult(
            status=aggregate_status,
            latency_ms=total_latency,
            details=details,
            error="; ".join(errors) if errors else None,
            check_name=self._name,
            component="aggregate",
        )

        # Cache last result
        async with self._lock:
            self._last_result = result

        return result

    async def _run_single_check(
        self,
        name: str,
        check_fn: HealthCheckFn,
        security_context: SecurityContext,
        timeout: float,
    ) -> HealthCheckResult:
        """
        Run a single health check with timeout.

        Args:
            name: Check name
            check_fn: Check function
            security_context: Security context
            timeout: Timeout in seconds

        Returns:
            HealthCheckResult from the check
        """
        start_time = time.perf_counter()

        try:
            result = await asyncio.wait_for(
                check_fn(security_context),
                timeout=timeout,
            )

            # Ensure check name is set
            if result.check_name is None:
                result = HealthCheckResult(
                    status=result.status,
                    latency_ms=result.latency_ms or (time.perf_counter() - start_time) * 1000,
                    details=result.details,
                    timestamp=result.timestamp,
                    error=result.error,
                    check_name=name,
                    component=result.component,
                )

            return result

        except TimeoutError:
            latency = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult.unhealthy(
                error=f"Health check timed out after {timeout}s",
                latency_ms=latency,
                check_name=name,
            )
        except (OSError, ConnectionError, RuntimeError, ValueError, TimeoutError) as e:
            latency = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult.unhealthy(
                error=str(e),
                latency_ms=latency,
                check_name=name,
                details={"exception_type": type(e).__name__},
            )

    def _aggregate_status(
        self,
        results: dict[str, HealthCheckResult],
    ) -> HealthStatus:
        """
        Determine aggregate status from individual results.

        Uses worst-case aggregation: any UNHEALTHY makes overall UNHEALTHY,
        any DEGRADED (without UNHEALTHY) makes overall DEGRADED.

        Args:
            results: Individual check results

        Returns:
            Aggregate HealthStatus
        """
        if not results:
            return HealthStatus.UNKNOWN

        statuses = [r.status for r in results.values()]

        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY

        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED

        if HealthStatus.UNKNOWN in statuses:
            # All checks must be HEALTHY or UNKNOWN
            if all(s in (HealthStatus.HEALTHY, HealthStatus.UNKNOWN) for s in statuses):
                # If all are UNKNOWN, return UNKNOWN
                if all(s == HealthStatus.UNKNOWN for s in statuses):
                    return HealthStatus.UNKNOWN
                # Some healthy, some unknown - consider healthy
                return HealthStatus.HEALTHY

        return HealthStatus.HEALTHY

    async def get_status(self) -> HealthStatus:
        """
        Get the last known health status without running checks.

        Returns:
            Last known HealthStatus or UNKNOWN if never checked

        Example:
            ```python
            status = await checker.get_status()
            if status == HealthStatus.UNHEALTHY:
                logger.warning("Service may be unhealthy")
            ```
        """
        async with self._lock:
            if self._last_result is None:
                return HealthStatus.UNKNOWN
            return self._last_result.status

    async def get_last_result(self) -> HealthCheckResult | None:
        """
        Get the last health check result.

        Returns:
            Last HealthCheckResult or None if never checked

        Example:
            ```python
            last_result = await checker.get_last_result()
            if last_result:
                age = datetime.now() - last_result.timestamp
                if age.seconds > 60:
                    print("Health check is stale")
            ```
        """
        async with self._lock:
            return self._last_result

    async def check_single(
        self,
        name: str,
        security_context: SecurityContext,
        *,
        timeout_seconds: float | None = None,
    ) -> HealthCheckResult:
        """
        Execute a single named health check.

        Args:
            name: Name of the check to execute
            security_context: Security context with health.check permission
            timeout_seconds: Override default timeout

        Returns:
            HealthCheckResult from the specified check

        Raises:
            AuthorizationError: If user lacks health.check permission
            ValidationError: If check name is not registered

        Example:
            ```python
            result = await checker.check_single(
                "database",
                security_context,
            )
            if not result.is_healthy:
                await reconnect_database()
            ```
        """
        # Check permission
        if not security_context.has_permission(self.PERMISSION_CHECK):
            raise AuthorizationError(
                message=f"Permission denied: {self.PERMISSION_CHECK}",
                required_permission=self.PERMISSION_CHECK,
                resource=f"health_checker:{self._name}:{name}",
                user_id=security_context.user_id,
            )

        if name not in self._checks:
            raise ValidationError(
                message=f"Health check '{name}' is not registered",
                suggestions=[
                    f"Available checks: {list(self._checks.keys())}",
                    "Register the check before using it",
                ],
            )

        timeout = timeout_seconds or self._timeout_seconds
        check_fn = self._checks[name]

        return await self._run_single_check(name, check_fn, security_context, timeout)


class CompositeHealthChecker:
    """
    Health checker that aggregates multiple HealthChecker instances.

    Useful for checking health across multiple systems or layers.

    Example:
        ```python
        # Create individual checkers
        db_checker = HealthChecker(name="databases")
        cache_checker = HealthChecker(name="caches")
        api_checker = HealthChecker(name="external_apis")

        # Create composite
        composite = CompositeHealthChecker(name="full_system")
        composite.add_checker(db_checker)
        composite.add_checker(cache_checker)
        composite.add_checker(api_checker)

        # Check all
        result = await composite.check(context)
        print(f"System status: {result.status.value}")
        ```
    """

    def __init__(
        self,
        name: str = "composite",
        timeout_seconds: float = 30.0,
    ) -> None:
        """
        Initialize composite health checker.

        Args:
            name: Name for this composite checker
            timeout_seconds: Total timeout for all checks
        """
        self._name = name
        self._timeout_seconds = timeout_seconds
        self._checkers: dict[str, HealthChecker] = {}

    @property
    def name(self) -> str:
        """Return composite checker name."""
        return self._name

    def add_checker(self, checker: HealthChecker) -> None:
        """
        Add a health checker to the composite.

        Args:
            checker: HealthChecker to add

        Raises:
            ValidationError: If checker name conflicts
        """
        if checker.name in self._checkers:
            raise ValidationError(
                message=f"Checker '{checker.name}' already exists",
                suggestions=["Use a different checker name"],
            )
        self._checkers[checker.name] = checker

    def remove_checker(self, name: str) -> bool:
        """
        Remove a health checker from the composite.

        Args:
            name: Name of checker to remove

        Returns:
            True if removed, False if not found
        """
        if name in self._checkers:
            del self._checkers[name]
            return True
        return False

    async def check(
        self,
        security_context: SecurityContext,
        *,
        timeout_seconds: float | None = None,
    ) -> HealthCheckResult:
        """
        Execute all registered health checkers.

        Args:
            security_context: Security context with health.check permission
            timeout_seconds: Override default timeout

        Returns:
            Aggregate HealthCheckResult

        Example:
            ```python
            result = await composite.check(context)

            for checker_name, checker_result in result.details.get("checkers", {}).items():
                print(f"{checker_name}: {checker_result['status']}")
            ```
        """
        if not self._checkers:
            return HealthCheckResult.unknown(
                reason="No health checkers registered",
                check_name=self._name,
            )

        timeout = timeout_seconds or self._timeout_seconds
        start_time = time.perf_counter()

        # Execute all checkers in parallel
        tasks = {
            name: checker.check(security_context, timeout_seconds=timeout / 2)
            for name, checker in self._checkers.items()
        }

        results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
        checker_results: dict[str, HealthCheckResult] = {}

        for name, result in zip(tasks.keys(), results_list):
            if isinstance(result, Exception):
                checker_results[name] = HealthCheckResult.unhealthy(
                    error=str(result),
                    check_name=name,
                )
            else:
                checker_results[name] = result

        # Aggregate status
        aggregate_status = self._aggregate_status(checker_results)

        total_latency = (time.perf_counter() - start_time) * 1000

        # Collect errors
        errors: list[str] = []
        for name, result in checker_results.items():
            if result.error and result.status != HealthStatus.HEALTHY:
                errors.append(f"{name}: {result.error}")

        details: dict[str, Any] = {
            "checkers": {name: result.to_dict() for name, result in checker_results.items()},
            "total_checkers": len(checker_results),
        }

        return HealthCheckResult(
            status=aggregate_status,
            latency_ms=total_latency,
            details=details,
            error="; ".join(errors) if errors else None,
            check_name=self._name,
            component="composite",
        )

    def _aggregate_status(
        self,
        results: dict[str, HealthCheckResult],
    ) -> HealthStatus:
        """Aggregate status from checker results."""
        if not results:
            return HealthStatus.UNKNOWN

        statuses = [r.status for r in results.values()]

        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY

        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED

        if all(s == HealthStatus.UNKNOWN for s in statuses):
            return HealthStatus.UNKNOWN

        return HealthStatus.HEALTHY


# Utility functions for creating common health checks


async def create_ping_check(
    name: str,
    ping_fn: Callable[[], Coroutine[Any, Any, bool]],
    timeout_ms: float = 1000.0,
) -> HealthCheckFn:
    """
    Create a simple ping-based health check.

    Args:
        name: Check name
        ping_fn: Async function that returns True if healthy
        timeout_ms: Expected max latency in milliseconds

    Returns:
        Health check function

    Example:
        ```python
        async def ping_redis():
            return await redis_client.ping()

        check_fn = await create_ping_check(
            "redis",
            ping_redis,
            timeout_ms=100,
        )
        checker.register_check("redis", check_fn)
        ```
    """

    async def check(security_context: SecurityContext) -> HealthCheckResult:
        start = time.perf_counter()
        try:
            result = await ping_fn()
            latency = (time.perf_counter() - start) * 1000

            if result:
                if latency > timeout_ms:
                    return HealthCheckResult.degraded(
                        reason=f"High latency: {latency:.1f}ms > {timeout_ms}ms",
                        latency_ms=latency,
                        check_name=name,
                    )
                return HealthCheckResult.healthy(
                    latency_ms=latency,
                    check_name=name,
                )
            else:
                return HealthCheckResult.unhealthy(
                    error="Ping returned false",
                    latency_ms=latency,
                    check_name=name,
                )
        except (OSError, ConnectionError, RuntimeError, ValueError, TimeoutError) as e:
            latency = (time.perf_counter() - start) * 1000
            return HealthCheckResult.unhealthy(
                error=str(e),
                latency_ms=latency,
                check_name=name,
            )

    return check
