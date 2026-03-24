"""
Recovery manager for automatic recovery procedures.

This module provides automatic recovery management with state restoration
and recovery procedures.

Example:
    ```python
    from yoda_foundation.resilience.recovery import RecoveryManager

    # Create recovery manager
    recovery_manager = RecoveryManager()

    # Register recovery procedure
    recovery_manager.register_procedure(
        name="database",
        recovery_func=recover_database,
        priority=1,
    )

    # Execute with recovery
    result = await recovery_manager.execute_with_recovery(
        func=database_operation,
        recovery_name="database",
        security_context=context,
    )

    # Or trigger manual recovery
    await recovery_manager.recover(
        name="database",
        security_context=context,
    )
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
    TypeVar,
)

from yoda_foundation.exceptions import (
    RecoveryError,
    StateRecoveryError,
)
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.resilience.recovery.checkpoint_manager import CheckpointManager
from yoda_foundation.security.context import SecurityContext


T = TypeVar("T")

logger = logging.getLogger(__name__)


class RecoveryStatus(Enum):
    """Recovery procedure status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class RecoveryProcedure:
    """
    Configuration for a recovery procedure.

    Attributes:
        name: Procedure name
        recovery_func: Async function to perform recovery
        priority: Recovery priority (lower = higher priority)
        max_attempts: Maximum recovery attempts
        timeout_ms: Recovery timeout in milliseconds
        cooldown_ms: Minimum time between recovery attempts
        enabled: Whether the procedure is enabled
        metadata: Additional metadata

    Example:
        ```python
        procedure = RecoveryProcedure(
            name="database",
            recovery_func=recover_database,
            priority=1,
            max_attempts=3,
            timeout_ms=30000,
        )
        ```
    """

    name: str
    recovery_func: Callable[[dict[str, Any]], Awaitable[bool]]
    priority: int = 0
    max_attempts: int = 3
    timeout_ms: int = 30000
    cooldown_ms: int = 5000
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryAttempt:
    """
    Record of a recovery attempt.

    Attributes:
        procedure_name: Procedure that was executed
        status: Attempt status
        attempt_number: Which attempt this was
        started_at: When the attempt started
        completed_at: When the attempt completed
        duration_ms: Duration in milliseconds
        error: Error message if failed
        state_restored: State that was restored
        metadata: Additional metadata

    Example:
        ```python
        attempt = RecoveryAttempt(
            procedure_name="database",
            status=RecoveryStatus.SUCCEEDED,
            attempt_number=2,
            started_at=datetime.now(timezone.utc),
            duration_ms=1500,
        )
        ```
    """

    procedure_name: str
    status: RecoveryStatus
    attempt_number: int
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    error: str | None = None
    state_restored: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryResult:
    """
    Result of recovery operation.

    Attributes:
        success: Whether recovery succeeded
        procedure_name: Procedure that was executed
        attempts: List of recovery attempts
        total_attempts: Total number of attempts
        total_duration_ms: Total recovery duration
        final_state: Final state after recovery
        error: Final error message if failed

    Example:
        ```python
        result = await recovery_manager.recover(
            name="database",
            security_context=context,
        )
        if result.success:
            print(f"Recovered after {result.total_attempts} attempts")
        else:
            print(f"Recovery failed: {result.error}")
        ```
    """

    success: bool
    procedure_name: str
    attempts: list[RecoveryAttempt]
    total_attempts: int
    total_duration_ms: float
    final_state: dict[str, Any] | None = None
    error: str | None = None


class RecoveryManager:
    """
    Manager for automatic recovery procedures.

    Manages recovery procedures for restoring system state
    and recovering from failures.

    Attributes:
        checkpoint_manager: Checkpoint manager for state persistence

    Example:
        ```python
        recovery_manager = RecoveryManager(
            checkpoint_manager=checkpoint_mgr,
        )

        # Register recovery procedures
        recovery_manager.register_procedure(
            name="database",
            recovery_func=recover_database,
            priority=1,
            max_attempts=3,
        )

        recovery_manager.register_procedure(
            name="cache",
            recovery_func=recover_cache,
            priority=2,
        )

        # Execute with automatic recovery
        result = await recovery_manager.execute_with_recovery(
            func=critical_operation,
            recovery_name="database",
            security_context=context,
        )

        # Or trigger recovery on failure
        try:
            await critical_operation()
        except Exception as e:
            await recovery_manager.recover(
                name="database",
                state={"last_error": str(e)},
                security_context=context,
            )
        ```
    """

    def __init__(
        self,
        checkpoint_manager: CheckpointManager | None = None,
        max_concurrent_recoveries: int = 5,
    ) -> None:
        """
        Initialize recovery manager.

        Args:
            checkpoint_manager: Checkpoint manager for state persistence
            max_concurrent_recoveries: Maximum concurrent recovery operations
        """
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()
        self.max_concurrent_recoveries = max_concurrent_recoveries

        self._procedures: dict[str, RecoveryProcedure] = {}
        self._recovery_history: list[RecoveryAttempt] = []
        self._last_recovery_time: dict[str, datetime] = {}
        self._active_recoveries: set[str] = set()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent_recoveries)

    def register_procedure(
        self,
        name: str,
        recovery_func: Callable[[dict[str, Any]], Awaitable[bool]],
        priority: int = 0,
        max_attempts: int = 3,
        timeout_ms: int = 30000,
        cooldown_ms: int = 5000,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Register a recovery procedure.

        Args:
            name: Procedure name
            recovery_func: Async function that performs recovery
            priority: Recovery priority (lower = higher priority)
            max_attempts: Maximum recovery attempts
            timeout_ms: Recovery timeout in milliseconds
            cooldown_ms: Minimum time between recovery attempts
            metadata: Additional metadata

        Example:
            ```python
            async def recover_database(state: Dict[str, Any]) -> bool:
                try:
                    await db.reconnect()
                    return True
                except Exception:
                    return False

            recovery_manager.register_procedure(
                name="database",
                recovery_func=recover_database,
                priority=1,
                max_attempts=3,
            )
            ```
        """
        self._procedures[name] = RecoveryProcedure(
            name=name,
            recovery_func=recovery_func,
            priority=priority,
            max_attempts=max_attempts,
            timeout_ms=timeout_ms,
            cooldown_ms=cooldown_ms,
            metadata=metadata or {},
        )

        logger.debug(
            f"Registered recovery procedure: {name} (priority={priority})",
            extra={"procedure_name": name, "priority": priority},
        )

    def unregister_procedure(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> None:
        """
        Unregister a recovery procedure.

        Args:
            name: Procedure name
            security_context: Security context

        Example:
            ```python
            recovery_manager.unregister_procedure(
                name="deprecated_recovery",
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_recovery")

        if name in self._procedures:
            del self._procedures[name]
            logger.info(
                f"Unregistered recovery procedure: {name}",
                extra={"procedure_name": name},
            )

    async def recover(
        self,
        name: str,
        security_context: SecurityContext,
        state: dict[str, Any] | None = None,
        force: bool = False,
    ) -> RecoveryResult:
        """
        Execute recovery procedure.

        Args:
            name: Procedure name
            security_context: Security context
            state: State to pass to recovery function
            force: Whether to ignore cooldown

        Returns:
            RecoveryResult with recovery details

        Raises:
            RecoveryError: If procedure not found or recovery fails

        Example:
            ```python
            result = await recovery_manager.recover(
                name="database",
                state={"connection_id": "conn_123"},
                security_context=context,
            )

            if result.success:
                print(f"Recovered after {result.total_attempts} attempts")
            else:
                print(f"Recovery failed: {result.error}")
            ```
        """
        procedure = self._procedures.get(name)
        if not procedure:
            raise RecoveryError(
                message=f"Recovery procedure '{name}' not found",
                recovery_point=name,
            )

        if not procedure.enabled:
            return RecoveryResult(
                success=False,
                procedure_name=name,
                attempts=[],
                total_attempts=0,
                total_duration_ms=0,
                error="Recovery procedure is disabled",
            )

        # Check cooldown
        if not force:
            async with self._lock:
                last_recovery = self._last_recovery_time.get(name)
                if last_recovery:
                    elapsed = (datetime.now(UTC) - last_recovery).total_seconds() * 1000
                    if elapsed < procedure.cooldown_ms:
                        remaining = procedure.cooldown_ms - elapsed
                        return RecoveryResult(
                            success=False,
                            procedure_name=name,
                            attempts=[],
                            total_attempts=0,
                            total_duration_ms=0,
                            error=f"Recovery in cooldown: {remaining:.0f}ms remaining",
                        )

        # Check if already in progress
        async with self._lock:
            if name in self._active_recoveries:
                return RecoveryResult(
                    success=False,
                    procedure_name=name,
                    attempts=[],
                    total_attempts=0,
                    total_duration_ms=0,
                    error="Recovery already in progress",
                )
            self._active_recoveries.add(name)

        state = state or {}
        attempts: list[RecoveryAttempt] = []
        start_time = datetime.now(UTC)

        try:
            async with self._semaphore:
                for attempt_num in range(1, procedure.max_attempts + 1):
                    attempt = await self._execute_attempt(
                        procedure=procedure,
                        attempt_number=attempt_num,
                        state=state,
                    )
                    attempts.append(attempt)

                    # Record attempt
                    async with self._lock:
                        self._recovery_history.append(attempt)

                    if attempt.status == RecoveryStatus.SUCCEEDED:
                        # Recovery succeeded
                        async with self._lock:
                            self._last_recovery_time[name] = datetime.now(UTC)

                        total_duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

                        logger.info(
                            f"Recovery '{name}' succeeded after {attempt_num} attempts",
                            extra={
                                "procedure_name": name,
                                "attempts": attempt_num,
                                "duration_ms": total_duration,
                            },
                        )

                        return RecoveryResult(
                            success=True,
                            procedure_name=name,
                            attempts=attempts,
                            total_attempts=attempt_num,
                            total_duration_ms=total_duration,
                            final_state=state,
                        )

                    # Wait before retry (except for last attempt)
                    if attempt_num < procedure.max_attempts:
                        await asyncio.sleep(1.0)  # Brief delay between attempts

                # All attempts exhausted
                total_duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

                last_error = attempts[-1].error if attempts else "Unknown error"

                logger.error(
                    f"Recovery '{name}' failed after {procedure.max_attempts} attempts",
                    extra={
                        "procedure_name": name,
                        "attempts": procedure.max_attempts,
                        "duration_ms": total_duration,
                        "error": last_error,
                    },
                )

                return RecoveryResult(
                    success=False,
                    procedure_name=name,
                    attempts=attempts,
                    total_attempts=procedure.max_attempts,
                    total_duration_ms=total_duration,
                    error=last_error,
                )

        finally:
            async with self._lock:
                self._active_recoveries.discard(name)

    async def _execute_attempt(
        self,
        procedure: RecoveryProcedure,
        attempt_number: int,
        state: dict[str, Any],
    ) -> RecoveryAttempt:
        """
        Execute a single recovery attempt.

        Runs the recovery procedure function with timeout handling
        and captures the result, duration, and any errors.

        Args:
            procedure: The recovery procedure configuration.
            attempt_number: The current attempt number (1-indexed).
            state: State dictionary to pass to the recovery function.

        Returns:
            RecoveryAttempt record with status, duration, and error details.
        """
        start_time = datetime.now(UTC)

        try:
            timeout_seconds = procedure.timeout_ms / 1000.0

            success = await asyncio.wait_for(
                procedure.recovery_func(state),
                timeout=timeout_seconds,
            )

            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            if success:
                return RecoveryAttempt(
                    procedure_name=procedure.name,
                    status=RecoveryStatus.SUCCEEDED,
                    attempt_number=attempt_number,
                    started_at=start_time,
                    completed_at=datetime.now(UTC),
                    duration_ms=duration_ms,
                    state_restored=state,
                )
            else:
                return RecoveryAttempt(
                    procedure_name=procedure.name,
                    status=RecoveryStatus.FAILED,
                    attempt_number=attempt_number,
                    started_at=start_time,
                    completed_at=datetime.now(UTC),
                    duration_ms=duration_ms,
                    error="Recovery function returned False",
                )

        except TimeoutError:
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            return RecoveryAttempt(
                procedure_name=procedure.name,
                status=RecoveryStatus.FAILED,
                attempt_number=attempt_number,
                started_at=start_time,
                completed_at=datetime.now(UTC),
                duration_ms=duration_ms,
                error=f"Recovery timed out after {procedure.timeout_ms}ms",
            )

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
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            return RecoveryAttempt(
                procedure_name=procedure.name,
                status=RecoveryStatus.FAILED,
                attempt_number=attempt_number,
                started_at=start_time,
                completed_at=datetime.now(UTC),
                duration_ms=duration_ms,
                error=str(e),
            )

    async def execute_with_recovery(
        self,
        func: Callable[..., Awaitable[T]],
        recovery_name: str,
        security_context: SecurityContext,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        auto_recover: bool = True,
    ) -> T:
        """
        Execute function with automatic recovery on failure.

        Args:
            func: Async function to execute
            recovery_name: Name of recovery procedure to use
            security_context: Security context
            args: Positional arguments
            kwargs: Keyword arguments
            auto_recover: Whether to auto-recover on failure

        Returns:
            Function result

        Raises:
            Exception: If function and recovery both fail

        Example:
            ```python
            result = await recovery_manager.execute_with_recovery(
                func=database_query,
                recovery_name="database",
                args=(query,),
                security_context=context,
            )
            ```
        """
        kwargs = kwargs or {}

        try:
            return await func(*args, **kwargs)

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
            if not auto_recover:
                raise

            logger.warning(
                f"Operation failed, attempting recovery '{recovery_name}'",
                extra={
                    "recovery_name": recovery_name,
                    "error": str(e),
                },
            )

            # Attempt recovery
            recovery_result = await self.recover(
                name=recovery_name,
                security_context=security_context,
                state={"error": str(e), "error_type": type(e).__name__},
            )

            if recovery_result.success:
                # Retry operation after recovery
                logger.info(
                    "Recovery succeeded, retrying operation",
                    extra={"recovery_name": recovery_name},
                )
                return await func(*args, **kwargs)
            else:
                # Recovery failed, re-raise original error
                raise StateRecoveryError(
                    checkpoint_id=recovery_name,
                    state_type="operation",
                    reason=f"Recovery failed: {recovery_result.error}",
                    cause=e,
                )

    async def recover_all(
        self,
        security_context: SecurityContext,
        state: dict[str, Any] | None = None,
    ) -> dict[str, RecoveryResult]:
        """
        Execute all recovery procedures in priority order.

        Args:
            security_context: Security context
            state: State to pass to recovery functions

        Returns:
            Dictionary mapping procedure names to results

        Example:
            ```python
            results = await recovery_manager.recover_all(security_context=context)
            for name, result in results.items():
                status = "OK" if result.success else "FAILED"
                print(f"{name}: {status}")
            ```
        """
        security_context.require_permission("resilience.manage_recovery")

        # Sort procedures by priority
        sorted_procedures = sorted(
            self._procedures.values(),
            key=lambda p: p.priority,
        )

        results = {}
        for procedure in sorted_procedures:
            if procedure.enabled:
                results[procedure.name] = await self.recover(
                    name=procedure.name,
                    security_context=security_context,
                    state=state,
                )

        return results

    async def get_history(
        self,
        security_context: SecurityContext,
        procedure_name: str | None = None,
        limit: int = 100,
    ) -> list[RecoveryAttempt]:
        """
        Get recovery history.

        Args:
            security_context: Security context
            procedure_name: Optional procedure filter
            limit: Maximum number of records

        Returns:
            List of recovery attempts

        Example:
            ```python
            history = await recovery_manager.get_history(
                security_context=context,
                procedure_name="database",
                limit=10,
            )
            for attempt in history:
                print(f"{attempt.started_at}: {attempt.status.value}")
            ```
        """
        async with self._lock:
            history = self._recovery_history.copy()

        if procedure_name:
            history = [a for a in history if a.procedure_name == procedure_name]

        return history[-limit:]

    async def clear_history(
        self,
        security_context: SecurityContext,
    ) -> None:
        """
        Clear recovery history.

        Args:
            security_context: Security context

        Example:
            ```python
            await recovery_manager.clear_history(security_context=context)
            ```
        """
        security_context.require_permission("resilience.manage_recovery")

        async with self._lock:
            self._recovery_history.clear()

        logger.info("Recovery history cleared")

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"RecoveryManager("
            f"procedures={len(self._procedures)}, "
            f"active={len(self._active_recoveries)})"
        )
