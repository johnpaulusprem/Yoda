"""
Health checker for component health monitoring.

This module provides health checking capabilities for monitoring
component and dependency health.

Example:
    ```python
    from yoda_foundation.resilience.health import HealthChecker

    # Create health checker
    health_checker = HealthChecker()

    # Register checks
    health_checker.register_check(
        name="database",
        check_func=check_database,
        critical=True,
    )

    # Check health
    result = await health_checker.check_health(security_context=context)
    print(f"Status: {result.status.value}")
    for component in result.components:
        print(f"  {component.name}: {component.status.value}")
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

from yoda_foundation.exceptions import (
    ValidationError,
)
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.security.context import SecurityContext


logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """
    Configuration for a health check.

    Attributes:
        name: Check name
        check_func: Async function that returns health status
        critical: Whether this check is critical for overall health
        timeout_ms: Check timeout in milliseconds
        interval_ms: Minimum interval between checks
        enabled: Whether the check is enabled
        metadata: Additional metadata

    Example:
        ```python
        check = HealthCheck(
            name="database",
            check_func=check_database,
            critical=True,
            timeout_ms=5000,
        )
        ```
    """

    name: str
    check_func: Callable[[], Awaitable[bool]]
    critical: bool = False
    timeout_ms: int = 5000
    interval_ms: int = 1000
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComponentHealth:
    """
    Health status of a single component.

    Attributes:
        name: Component name
        status: Health status
        latency_ms: Check latency in milliseconds
        message: Optional status message
        error: Optional error message
        last_check: When the check was performed
        consecutive_failures: Number of consecutive failures
        metadata: Additional metadata

    Example:
        ```python
        health = ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            latency_ms=45.5,
            last_check=datetime.now(timezone.utc),
        )
        ```
    """

    name: str
    status: HealthStatus
    latency_ms: float = 0.0
    message: str | None = None
    error: str | None = None
    last_check: datetime = field(default_factory=lambda: datetime.now(UTC))
    consecutive_failures: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthCheckResult:
    """
    Overall health check result.

    Attributes:
        status: Overall health status
        components: List of component health statuses
        total_checks: Total number of checks performed
        healthy_checks: Number of healthy checks
        degraded_checks: Number of degraded checks
        unhealthy_checks: Number of unhealthy checks
        check_duration_ms: Total check duration
        timestamp: When the check was performed

    Example:
        ```python
        result = await health_checker.check_health(security_context=context)
        print(f"Overall: {result.status.value}")
        print(f"Healthy: {result.healthy_checks}/{result.total_checks}")
        ```
    """

    status: HealthStatus
    components: list[ComponentHealth]
    total_checks: int
    healthy_checks: int
    degraded_checks: int
    unhealthy_checks: int
    check_duration_ms: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_healthy(self) -> bool:
        """Check if overall status is healthy."""
        return self.status == HealthStatus.HEALTHY

    @property
    def critical_components_healthy(self) -> bool:
        """Check if all critical components are healthy."""
        return self.unhealthy_checks == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status.value,
            "components": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "latency_ms": c.latency_ms,
                    "message": c.message,
                    "error": c.error,
                    "last_check": c.last_check.isoformat(),
                }
                for c in self.components
            ],
            "total_checks": self.total_checks,
            "healthy_checks": self.healthy_checks,
            "degraded_checks": self.degraded_checks,
            "unhealthy_checks": self.unhealthy_checks,
            "check_duration_ms": self.check_duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }


class HealthChecker:
    """
    Health checker for component monitoring.

    Monitors health of registered components and dependencies.

    Attributes:
        default_timeout_ms: Default timeout for health checks
        parallel_checks: Whether to run checks in parallel

    Example:
        ```python
        health_checker = HealthChecker(
            default_timeout_ms=5000,
            parallel_checks=True,
        )

        # Register checks
        health_checker.register_check(
            name="database",
            check_func=check_database,
            critical=True,
        )
        health_checker.register_check(
            name="cache",
            check_func=check_cache,
            critical=False,
        )
        health_checker.register_check(
            name="external_api",
            check_func=check_api,
            timeout_ms=10000,
        )

        # Check health
        result = await health_checker.check_health(security_context=context)

        if result.is_healthy:
            print("All systems operational")
        elif result.status == HealthStatus.DEGRADED:
            print("Some non-critical systems degraded")
        else:
            print("Critical systems unhealthy!")
        ```
    """

    def __init__(
        self,
        default_timeout_ms: int = 5000,
        parallel_checks: bool = True,
        cache_duration_ms: int = 1000,
    ) -> None:
        """
        Initialize health checker.

        Args:
            default_timeout_ms: Default timeout for health checks
            parallel_checks: Whether to run checks in parallel
            cache_duration_ms: Duration to cache health results

        Raises:
            ValidationError: If parameters are invalid
        """
        if default_timeout_ms <= 0:
            raise ValidationError(
                message=f"default_timeout_ms must be positive, got {default_timeout_ms}",
                field_name="default_timeout_ms",
            )

        self.default_timeout_ms = default_timeout_ms
        self.parallel_checks = parallel_checks
        self.cache_duration_ms = cache_duration_ms

        self._checks: dict[str, HealthCheck] = {}
        self._last_results: dict[str, ComponentHealth] = {}
        self._last_check_time: dict[str, datetime] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._lock = asyncio.Lock()

    def register_check(
        self,
        name: str,
        check_func: Callable[[], Awaitable[bool]],
        critical: bool = False,
        timeout_ms: int | None = None,
        interval_ms: int = 1000,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Register a health check.

        Args:
            name: Check name
            check_func: Async function that returns True if healthy
            critical: Whether this check is critical
            timeout_ms: Check timeout in milliseconds
            interval_ms: Minimum interval between checks
            metadata: Additional metadata

        Example:
            ```python
            async def check_database() -> bool:
                try:
                    await db.execute("SELECT 1")
                    return True
                except Exception:
                    return False

            health_checker.register_check(
                name="database",
                check_func=check_database,
                critical=True,
                timeout_ms=3000,
            )
            ```
        """
        self._checks[name] = HealthCheck(
            name=name,
            check_func=check_func,
            critical=critical,
            timeout_ms=timeout_ms or self.default_timeout_ms,
            interval_ms=interval_ms,
            metadata=metadata or {},
        )
        self._consecutive_failures[name] = 0

        logger.debug(
            f"Registered health check: {name} (critical={critical})",
            extra={"check_name": name, "critical": critical},
        )

    def unregister_check(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> None:
        """
        Unregister a health check.

        Args:
            name: Check name
            security_context: Security context

        Example:
            ```python
            health_checker.unregister_check(
                name="deprecated_service",
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_health")

        if name in self._checks:
            del self._checks[name]
            self._last_results.pop(name, None)
            self._last_check_time.pop(name, None)
            self._consecutive_failures.pop(name, None)

            logger.info(
                f"Unregistered health check: {name}",
                extra={"check_name": name},
            )

    async def check_health(
        self,
        security_context: SecurityContext,
        include_details: bool = True,
    ) -> HealthCheckResult:
        """
        Check health of all registered components.

        Args:
            security_context: Security context
            include_details: Whether to include detailed component results

        Returns:
            HealthCheckResult with overall and component health

        Example:
            ```python
            result = await health_checker.check_health(security_context=context)

            if result.is_healthy:
                print("All healthy!")
            else:
                for component in result.components:
                    if component.status != HealthStatus.HEALTHY:
                        print(f"{component.name}: {component.error}")
            ```
        """
        start_time = datetime.now(UTC)
        components: list[ComponentHealth] = []

        if self.parallel_checks:
            # Run checks in parallel
            tasks = [
                self._run_check(name, check)
                for name, check in self._checks.items()
                if check.enabled
            ]
            components = await asyncio.gather(*tasks)
        else:
            # Run checks sequentially
            for name, check in self._checks.items():
                if check.enabled:
                    component = await self._run_check(name, check)
                    components.append(component)

        # Calculate totals
        healthy = sum(1 for c in components if c.status == HealthStatus.HEALTHY)
        degraded = sum(1 for c in components if c.status == HealthStatus.DEGRADED)
        unhealthy = sum(1 for c in components if c.status == HealthStatus.UNHEALTHY)

        # Determine overall status based on critical components
        overall_status = self._determine_overall_status(components)

        check_duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        result = HealthCheckResult(
            status=overall_status,
            components=components if include_details else [],
            total_checks=len(components),
            healthy_checks=healthy,
            degraded_checks=degraded,
            unhealthy_checks=unhealthy,
            check_duration_ms=check_duration,
        )

        logger.info(
            f"Health check completed: {overall_status.value} ({healthy}/{len(components)} healthy)",
            extra={
                "status": overall_status.value,
                "healthy": healthy,
                "total": len(components),
                "duration_ms": check_duration,
            },
        )

        return result

    async def check_component(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> ComponentHealth | None:
        """
        Check health of a specific component.

        Args:
            name: Component name
            security_context: Security context

        Returns:
            ComponentHealth or None if not registered

        Example:
            ```python
            db_health = await health_checker.check_component(
                name="database",
                security_context=context,
            )
            if db_health and db_health.status != HealthStatus.HEALTHY:
                logger.error(f"Database unhealthy: {db_health.error}")
            ```
        """
        check = self._checks.get(name)
        if not check or not check.enabled:
            return None

        return await self._run_check(name, check)

    async def get_cached_health(
        self,
        security_context: SecurityContext,
    ) -> dict[str, ComponentHealth]:
        """
        Get cached health results.

        Args:
            security_context: Security context

        Returns:
            Dictionary of cached component health results

        Example:
            ```python
            cached = await health_checker.get_cached_health(security_context=context)
            for name, health in cached.items():
                print(f"{name}: {health.status.value}")
            ```
        """
        async with self._lock:
            return dict(self._last_results)

    async def _run_check(
        self,
        name: str,
        check: HealthCheck,
    ) -> ComponentHealth:
        """
        Run a single health check.

        Executes the check function with timeout handling, updates
        consecutive failure counts, caches results, and logs unhealthy
        status. Uses cached results if within the configured interval.

        Args:
            name: The health check name.
            check: The health check configuration.

        Returns:
            ComponentHealth with status, latency, and error details.
        """
        # Check if we should use cached result
        async with self._lock:
            last_check_time = self._last_check_time.get(name)
            if last_check_time:
                elapsed = (datetime.now(UTC) - last_check_time).total_seconds() * 1000
                if elapsed < check.interval_ms and name in self._last_results:
                    return self._last_results[name]

        start_time = datetime.now(UTC)
        status = HealthStatus.UNKNOWN
        error_message = None
        message = None

        try:
            timeout_seconds = check.timeout_ms / 1000.0
            is_healthy = await asyncio.wait_for(
                check.check_func(),
                timeout=timeout_seconds,
            )

            if is_healthy:
                status = HealthStatus.HEALTHY
                message = "Check passed"
                async with self._lock:
                    self._consecutive_failures[name] = 0
            else:
                status = HealthStatus.UNHEALTHY
                error_message = "Check returned unhealthy"
                async with self._lock:
                    self._consecutive_failures[name] += 1

        except TimeoutError:
            status = HealthStatus.UNHEALTHY
            error_message = f"Check timed out after {check.timeout_ms}ms"
            async with self._lock:
                self._consecutive_failures[name] += 1

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
            status = HealthStatus.UNHEALTHY
            error_message = str(e)
            async with self._lock:
                self._consecutive_failures[name] += 1

        latency_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

        async with self._lock:
            consecutive_failures = self._consecutive_failures.get(name, 0)

        component_health = ComponentHealth(
            name=name,
            status=status,
            latency_ms=latency_ms,
            message=message,
            error=error_message,
            last_check=start_time,
            consecutive_failures=consecutive_failures,
            metadata=check.metadata,
        )

        # Cache result
        async with self._lock:
            self._last_results[name] = component_health
            self._last_check_time[name] = start_time

        # Log unhealthy checks
        if status != HealthStatus.HEALTHY:
            logger.warning(
                f"Health check '{name}' {status.value}: {error_message}",
                extra={
                    "check_name": name,
                    "status": status.value,
                    "error": error_message,
                    "consecutive_failures": consecutive_failures,
                },
            )

        return component_health

    def _determine_overall_status(
        self,
        components: list[ComponentHealth],
    ) -> HealthStatus:
        """
        Determine overall health status from component health.

        Returns UNHEALTHY if any critical component is unhealthy,
        DEGRADED if non-critical components are unhealthy or degraded,
        and HEALTHY if all components pass their checks.

        Args:
            components: List of component health results.

        Returns:
            Overall HealthStatus based on component statuses.
        """
        if not components:
            return HealthStatus.UNKNOWN

        # Check critical components first
        critical_unhealthy = False
        any_unhealthy = False
        any_degraded = False

        for component in components:
            check = self._checks.get(component.name)
            is_critical = check.critical if check else False

            if component.status == HealthStatus.UNHEALTHY:
                any_unhealthy = True
                if is_critical:
                    critical_unhealthy = True
            elif component.status == HealthStatus.DEGRADED:
                any_degraded = True

        if critical_unhealthy:
            return HealthStatus.UNHEALTHY
        elif any_unhealthy or any_degraded:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY

    def __repr__(self) -> str:
        """Return string representation."""
        return f"HealthChecker(checks={len(self._checks)}, parallel={self.parallel_checks})"
