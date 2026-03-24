"""
Resilience exceptions for the Agentic AI Component Library.

This module provides exceptions for retry, circuit breaker, fallback,
and recovery mechanisms.

Example:
    ```python
    from yoda_foundation.exceptions import (
        RetryExhaustedError,
        CircuitBreakerOpenError,
        FallbackFailedError,
    )

    async def resilient_operation(params: dict):
        try:
            return await risky_api_call(params)
        except RetryExhaustedError as e:
            logger.error(f"All retries exhausted: {e.error_id}")
            raise FallbackFailedError(
                operation="risky_api_call",
                attempts=e.attempts,
            )
    ```
"""

from __future__ import annotations

from typing import Any

from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)


class ResilienceError(AgenticBaseException):
    """
    Base class for all resilience-related errors.

    Provides common attributes for resilience exceptions.

    Attributes:
        operation: The operation that failed
        component: The resilience component (retry, circuit_breaker, etc.)

    Example:
        ```python
        raise ResilienceError(
            message="Resilience mechanism failed",
            operation="api_call",
            component="retry",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Resilience error occurred",
        *,
        operation: str | None = None,
        component: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = False,
    ) -> None:
        """
        Initialize resilience error.

        Args:
            message: Human-readable error description
            operation: The operation that failed
            component: The resilience component
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
            severity: Error severity level
            retryable: Whether the operation can be retried
        """
        self.operation = operation
        self.component = component

        extra_details = {
            "operation": operation,
            "component": component,
        }

        merged_details = {**extra_details, **(details or {})}

        super().__init__(
            message=message,
            category=ErrorCategory.INTERNAL,
            severity=severity,
            retryable=retryable,
            user_message="A resilience error occurred. Please try again.",
            suggestions=suggestions or ["Retry the operation", "Contact support"],
            cause=cause,
            details=merged_details,
        )


class RetryError(ResilienceError):
    """
    Base class for retry-related errors.

    Attributes:
        attempts: Number of retry attempts made
        max_attempts: Maximum retry attempts allowed

    Example:
        ```python
        raise RetryError(
            message="Retry mechanism failed",
            attempts=3,
            max_attempts=5,
        )
        ```
    """

    def __init__(
        self,
        message: str = "Retry error occurred",
        *,
        attempts: int | None = None,
        max_attempts: int | None = None,
        operation: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = False,
    ) -> None:
        """
        Initialize retry error.

        Args:
            message: Human-readable error description
            attempts: Number of retry attempts made
            max_attempts: Maximum retry attempts allowed
            operation: The operation that failed
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
            severity: Error severity level
            retryable: Whether the operation can be retried
        """
        self.attempts = attempts
        self.max_attempts = max_attempts

        extra_details = {
            "attempts": attempts,
            "max_attempts": max_attempts,
        }

        merged_details = {**extra_details, **(details or {})}

        super().__init__(
            message=message,
            operation=operation,
            component="retry",
            suggestions=suggestions,
            cause=cause,
            details=merged_details,
            severity=severity,
            retryable=retryable,
        )


class RetryExhaustedError(RetryError):
    """
    Retry exhausted error.

    Raised when all retry attempts have been exhausted.

    Attributes:
        operation: The operation that failed
        attempts: Number of retry attempts made
        max_attempts: Maximum retry attempts allowed
        last_error: The last error encountered

    Example:
        ```python
        raise RetryExhaustedError(
            operation="api_call",
            attempts=5,
            max_attempts=5,
            last_error=connection_error,
        )
        ```
    """

    def __init__(
        self,
        message: str = "",
        *,
        operation: str,
        attempts: int,
        max_attempts: int,
        last_error: Exception | None = None,
        suggestions: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize retry exhausted error.

        Args:
            message: Human-readable error description (auto-generated if empty)
            operation: The operation that failed
            attempts: Number of retry attempts made
            max_attempts: Maximum retry attempts allowed
            last_error: The last error encountered
            suggestions: Actionable remediation steps
            details: Additional context
        """
        self.last_error = last_error

        if not message:
            message = (
                f"Retry exhausted for operation '{operation}'. "
                f"Attempted {attempts}/{max_attempts} times."
            )

        extra_details = {
            "last_error": str(last_error) if last_error else None,
        }

        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            f"Operation failed after {attempts} attempts",
            "Check system health and retry later",
            "Review error logs for failure patterns",
            "Consider increasing retry limits if appropriate",
        ]

        super().__init__(
            message=message,
            attempts=attempts,
            max_attempts=max_attempts,
            operation=operation,
            suggestions=suggestions or default_suggestions,
            cause=last_error,
            details=merged_details,
            severity=ErrorSeverity.HIGH,
            retryable=False,
        )
        self.user_message = f"Operation failed after {attempts} attempts. Please try again later."


class RetryBudgetExceededError(RetryError):
    """
    Retry budget exceeded error.

    Raised when retry budget (total retries across all operations) is exceeded.

    Attributes:
        current_retries: Current retry count
        budget_limit: Maximum retries allowed
        time_window: Time window for the budget

    Example:
        ```python
        raise RetryBudgetExceededError(
            current_retries=100,
            budget_limit=100,
            time_window="1 minute",
        )
        ```
    """

    def __init__(
        self,
        message: str = "",
        *,
        current_retries: int,
        budget_limit: int,
        time_window: str | None = None,
        suggestions: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize retry budget exceeded error.

        Args:
            message: Human-readable error description (auto-generated if empty)
            current_retries: Current retry count
            budget_limit: Maximum retries allowed
            time_window: Time window for the budget
            suggestions: Actionable remediation steps
            details: Additional context
        """
        self.current_retries = current_retries
        self.budget_limit = budget_limit
        self.time_window = time_window

        if not message:
            message = f"Retry budget exceeded: {current_retries}/{budget_limit}"
            if time_window:
                message += f" in {time_window}"

        extra_details = {
            "current_retries": current_retries,
            "budget_limit": budget_limit,
            "time_window": time_window,
            "http_status": 429,
        }

        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "Wait for retry budget to reset",
            "Reduce concurrent operations",
            "Investigate why so many retries are needed",
        ]

        super().__init__(
            message=message,
            suggestions=suggestions or default_suggestions,
            details=merged_details,
            severity=ErrorSeverity.HIGH,
            retryable=False,
        )
        self.user_message = "Too many retry attempts. Please try again later."


class CircuitBreakerError(ResilienceError):
    """
    Base class for circuit breaker errors.

    Attributes:
        circuit_name: Name of the circuit breaker
        state: Current state of the circuit breaker

    Example:
        ```python
        raise CircuitBreakerError(
            message="Circuit breaker error",
            circuit_name="api_client",
            state="open",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Circuit breaker error occurred",
        *,
        circuit_name: str | None = None,
        state: str | None = None,
        operation: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = True,
    ) -> None:
        """
        Initialize circuit breaker error.

        Args:
            message: Human-readable error description
            circuit_name: Name of the circuit breaker
            state: Current state of the circuit breaker
            operation: The operation that failed
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
            severity: Error severity level
            retryable: Whether the operation can be retried
        """
        self.circuit_name = circuit_name
        self.state = state

        extra_details = {
            "circuit_name": circuit_name,
            "state": state,
        }

        merged_details = {**extra_details, **(details or {})}

        super().__init__(
            message=message,
            operation=operation,
            component="circuit_breaker",
            suggestions=suggestions,
            cause=cause,
            details=merged_details,
            severity=severity,
            retryable=retryable,
        )


class CircuitBreakerOpenError(CircuitBreakerError):
    """
    Circuit breaker open error.

    Raised when an operation is blocked because the circuit breaker is open.

    Attributes:
        circuit_name: Name of the circuit breaker
        failure_count: Number of consecutive failures
        recovery_time: Estimated time until circuit may close

    Example:
        ```python
        raise CircuitBreakerOpenError(
            circuit_name="payment_api",
            failure_count=10,
            recovery_time="30 seconds",
        )
        ```
    """

    def __init__(
        self,
        message: str = "",
        *,
        circuit_name: str,
        failure_count: int,
        recovery_time: str | None = None,
        suggestions: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize circuit breaker open error.

        Args:
            message: Human-readable error description (auto-generated if empty)
            circuit_name: Name of the circuit breaker
            failure_count: Number of consecutive failures
            recovery_time: Estimated time until circuit may close
            suggestions: Actionable remediation steps
            details: Additional context
        """
        self.failure_count = failure_count
        self.recovery_time = recovery_time

        if not message:
            message = f"Circuit breaker '{circuit_name}' is open after {failure_count} failures."
            if recovery_time:
                message += f" Recovery in {recovery_time}."

        extra_details = {
            "failure_count": failure_count,
            "recovery_time": recovery_time,
            "http_status": 503,
        }

        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "Service is temporarily unavailable",
            f"Wait for recovery time: {recovery_time}" if recovery_time else "Wait and retry later",
            "Check service health status",
            "Use fallback mechanism if available",
        ]

        super().__init__(
            message=message,
            circuit_name=circuit_name,
            state="open",
            suggestions=suggestions or default_suggestions,
            details=merged_details,
            severity=ErrorSeverity.HIGH,
            retryable=True,
        )
        self.user_message = "Service is temporarily unavailable. Please try again later."


class FallbackError(ResilienceError):
    """
    Base class for fallback errors.

    Attributes:
        fallback_chain: List of fallback strategies attempted

    Example:
        ```python
        raise FallbackError(
            message="Fallback error",
            fallback_chain=["primary", "secondary"],
        )
        ```
    """

    def __init__(
        self,
        message: str = "Fallback error occurred",
        *,
        fallback_chain: list[str] | None = None,
        operation: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        retryable: bool = False,
    ) -> None:
        """
        Initialize fallback error.

        Args:
            message: Human-readable error description
            fallback_chain: List of fallback strategies attempted
            operation: The operation that failed
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
            severity: Error severity level
            retryable: Whether the operation can be retried
        """
        self.fallback_chain = fallback_chain or []

        extra_details = {
            "fallback_chain": fallback_chain,
        }

        merged_details = {**extra_details, **(details or {})}

        super().__init__(
            message=message,
            operation=operation,
            component="fallback",
            suggestions=suggestions,
            cause=cause,
            details=merged_details,
            severity=severity,
            retryable=retryable,
        )


class FallbackFailedError(FallbackError):
    """
    Fallback failed error.

    Raised when all fallback strategies have been exhausted.

    Attributes:
        operation: The operation that failed
        fallback_chain: List of fallback strategies attempted
        errors: List of errors from each fallback attempt

    Example:
        ```python
        raise FallbackFailedError(
            operation="get_user_data",
            fallback_chain=["primary_db", "cache", "default"],
            errors=[db_error, cache_error, None],
        )
        ```
    """

    def __init__(
        self,
        message: str = "",
        *,
        operation: str,
        fallback_chain: list[str],
        errors: list[Exception | None] | None = None,
        suggestions: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize fallback failed error.

        Args:
            message: Human-readable error description (auto-generated if empty)
            operation: The operation that failed
            fallback_chain: List of fallback strategies attempted
            errors: List of errors from each fallback attempt
            suggestions: Actionable remediation steps
            details: Additional context
        """
        self.errors = errors or []

        if not message:
            message = (
                f"All fallback strategies failed for operation '{operation}'. "
                f"Attempted: {', '.join(fallback_chain)}"
            )

        extra_details = {
            "errors": [str(e) if e else None for e in self.errors],
        }

        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "All fallback strategies exhausted",
            "Review each fallback error for patterns",
            "Check system health across all services",
            "Consider additional fallback options",
        ]

        super().__init__(
            message=message,
            fallback_chain=fallback_chain,
            operation=operation,
            suggestions=suggestions or default_suggestions,
            details=merged_details,
            severity=ErrorSeverity.CRITICAL,
            retryable=False,
        )
        self.user_message = "Operation failed. All alternatives have been exhausted."


class RecoveryError(ResilienceError):
    """
    Base class for recovery errors.

    Attributes:
        recovery_point: The recovery point that failed

    Example:
        ```python
        raise RecoveryError(
            message="Recovery error",
            recovery_point="checkpoint_123",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Recovery error occurred",
        *,
        recovery_point: str | None = None,
        operation: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
        severity: ErrorSeverity = ErrorSeverity.HIGH,
        retryable: bool = True,
    ) -> None:
        """
        Initialize recovery error.

        Args:
            message: Human-readable error description
            recovery_point: The recovery point that failed
            operation: The operation that failed
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
            severity: Error severity level
            retryable: Whether the operation can be retried
        """
        self.recovery_point = recovery_point

        extra_details = {
            "recovery_point": recovery_point,
        }

        merged_details = {**extra_details, **(details or {})}

        super().__init__(
            message=message,
            operation=operation,
            component="recovery",
            suggestions=suggestions,
            cause=cause,
            details=merged_details,
            severity=severity,
            retryable=retryable,
        )


class StateRecoveryError(RecoveryError):
    """
    State recovery error.

    Raised when state recovery fails.

    Attributes:
        checkpoint_id: The checkpoint ID that failed to restore
        state_type: Type of state being recovered

    Example:
        ```python
        raise StateRecoveryError(
            checkpoint_id="ckpt_123",
            state_type="agent_state",
            reason="Corrupted checkpoint data",
        )
        ```
    """

    def __init__(
        self,
        message: str = "",
        *,
        checkpoint_id: str,
        state_type: str | None = None,
        reason: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize state recovery error.

        Args:
            message: Human-readable error description (auto-generated if empty)
            checkpoint_id: The checkpoint ID that failed to restore
            state_type: Type of state being recovered
            reason: Reason for recovery failure
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.checkpoint_id = checkpoint_id
        self.state_type = state_type
        self.reason = reason

        if not message:
            message = f"Failed to recover state from checkpoint '{checkpoint_id}'"
            if reason:
                message += f": {reason}"

        extra_details = {
            "checkpoint_id": checkpoint_id,
            "state_type": state_type,
            "reason": reason,
        }

        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "Verify checkpoint data integrity",
            "Check storage availability",
            "Try an earlier checkpoint",
            "Review checkpoint creation logs",
        ]

        super().__init__(
            message=message,
            recovery_point=checkpoint_id,
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=merged_details,
            severity=ErrorSeverity.HIGH,
            retryable=True,
        )
        self.user_message = "Failed to restore previous state. Operation cannot continue."


class CheckpointError(RecoveryError):
    """
    Checkpoint error.

    Raised when checkpoint creation or management fails.

    Attributes:
        checkpoint_id: The checkpoint ID
        checkpoint_type: Type of checkpoint

    Example:
        ```python
        raise CheckpointError(
            checkpoint_id="ckpt_123",
            checkpoint_type="agent_state",
            reason="Storage full",
        )
        ```
    """

    def __init__(
        self,
        message: str = "",
        *,
        checkpoint_id: str,
        checkpoint_type: str | None = None,
        reason: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize checkpoint error.

        Args:
            message: Human-readable error description (auto-generated if empty)
            checkpoint_id: The checkpoint ID
            checkpoint_type: Type of checkpoint
            reason: Reason for checkpoint failure
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.checkpoint_id = checkpoint_id
        self.checkpoint_type = checkpoint_type
        self.reason = reason

        if not message:
            message = f"Checkpoint operation failed for '{checkpoint_id}'"
            if reason:
                message += f": {reason}"

        extra_details = {
            "checkpoint_id": checkpoint_id,
            "checkpoint_type": checkpoint_type,
            "reason": reason,
        }

        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "Check storage capacity",
            "Verify checkpoint permissions",
            "Review checkpoint configuration",
        ]

        super().__init__(
            message=message,
            recovery_point=checkpoint_id,
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=merged_details,
            severity=ErrorSeverity.MEDIUM,
            retryable=True,
        )
