"""
Event-specific exceptions for the Agentic AI Component Library.

This module defines exceptions related to event bus operations,
event handling, and event-driven workflows.

Example:
    ```python
    from yoda_foundation.exceptions import (
        EventPublishError,
        EventHandlerError,
        EventSubscriptionError,
    )

    try:
        await event_bus.publish(event, security_context)
    except EventPublishError as e:
        logger.error(f"Failed to publish event: {e}")
        if e.retryable:
            await retry_publish(event)
    ```
"""

from __future__ import annotations

from typing import Any

from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)


class EventError(AgenticBaseException):
    """
    Base exception for all event-related errors.

    All event-specific exceptions inherit from this class.

    Attributes:
        event_type: Type of event that caused the error
        event_id: Unique identifier of the event

    Example:
        ```python
        raise EventError(
            message="Event processing failed",
            event_type="agent.completed",
            event_id="evt_123",
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        event_type: str | None = None,
        event_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize event error.

        Args:
            message: Error description
            event_type: Type of event
            event_id: Event identifier
            **kwargs: Additional arguments for AgenticBaseException
        """
        super().__init__(
            message=message,
            category=ErrorCategory.INTERNAL,
            severity=ErrorSeverity.MEDIUM,
            **kwargs,
        )
        self.event_type = event_type
        self.event_id = event_id

        if event_type:
            self.details["event_type"] = event_type
        if event_id:
            self.details["event_id"] = event_id


class EventPublishError(EventError):
    """
    Raised when event publication fails.

    This error occurs when an event cannot be published to the event bus
    due to connection issues, serialization errors, or bus capacity.

    Attributes:
        reason: Specific reason for failure

    Example:
        ```python
        try:
            await bus.publish(event, security_context)
        except EventPublishError as e:
            if e.retryable:
                await asyncio.sleep(1)
                await bus.publish(event, security_context)
        ```

    Raises:
        This exception when event publication fails.
    """

    def __init__(
        self,
        message: str,
        *,
        event_type: str | None = None,
        event_id: str | None = None,
        reason: str | None = None,
        retryable: bool = True,
        cause: Exception | None = None,
    ) -> None:
        """
        Initialize publish error.

        Args:
            message: Error description
            event_type: Type of event
            event_id: Event identifier
            reason: Failure reason
            retryable: Whether operation can be retried
            cause: Original exception
        """
        super().__init__(
            message=message,
            event_type=event_type,
            event_id=event_id,
            severity=ErrorSeverity.HIGH,
            retryable=retryable,
            user_message="Failed to publish event. Please try again.",
            suggestions=[
                "Check event bus connection",
                "Verify event format",
                "Retry the operation",
            ],
            cause=cause,
        )
        self.reason = reason
        if reason:
            self.details["reason"] = reason


class EventSubscriptionError(EventError):
    """
    Raised when event subscription fails.

    This error occurs when subscribing to events fails due to
    invalid filters, permission issues, or bus errors.

    Attributes:
        subscription_id: Failed subscription identifier

    Example:
        ```python
        try:
            subscription_id = await bus.subscribe(
                "agent.*",
                handler,
                security_context=context,
            )
        except EventSubscriptionError as e:
            logger.error(f"Subscription failed: {e.suggestions}")
        ```

    Raises:
        This exception when event subscription fails.
    """

    def __init__(
        self,
        message: str,
        *,
        event_type: str | None = None,
        subscription_id: str | None = None,
        reason: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        """
        Initialize subscription error.

        Args:
            message: Error description
            event_type: Event type pattern
            subscription_id: Subscription identifier
            reason: Failure reason
            cause: Original exception
        """
        super().__init__(
            message=message,
            event_type=event_type,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message="Failed to subscribe to events.",
            suggestions=[
                "Verify event type pattern",
                "Check permissions",
                "Ensure handler is async",
            ],
            cause=cause,
        )
        self.subscription_id = subscription_id
        if subscription_id:
            self.details["subscription_id"] = subscription_id
        if reason:
            self.details["reason"] = reason


class EventHandlerError(EventError):
    """
    Raised when event handler execution fails.

    This error occurs when a registered handler fails to process
    an event. The error is isolated to prevent affecting other handlers.

    Attributes:
        handler_name: Name of the failed handler
        retry_count: Number of retries attempted

    Example:
        ```python
        class MyHandler(EventHandler):
            async def handle(
                self,
                event: Event,
                security_context: SecurityContext,
            ) -> None:
                try:
                    await process_event(event)
                except (RuntimeError, ConnectionError, TimeoutError, ValueError) as e:
                    raise EventHandlerError(
                        message="Processing failed",
                        event_type=event.event_type,
                        handler_name=self.name,
                        cause=e,
                    )
        ```

    Raises:
        This exception when event handler fails.
    """

    def __init__(
        self,
        message: str,
        *,
        event_type: str | None = None,
        event_id: str | None = None,
        handler_name: str | None = None,
        retry_count: int = 0,
        retryable: bool = True,
        cause: Exception | None = None,
    ) -> None:
        """
        Initialize handler error.

        Args:
            message: Error description
            event_type: Type of event
            event_id: Event identifier
            handler_name: Handler that failed
            retry_count: Retries attempted
            retryable: Whether operation can be retried
            cause: Original exception
        """
        super().__init__(
            message=message,
            event_type=event_type,
            event_id=event_id,
            severity=ErrorSeverity.MEDIUM,
            retryable=retryable,
            user_message="Event handler failed.",
            suggestions=[
                "Check handler logs",
                "Verify event data",
                "Handler will retry automatically" if retryable else "Manual intervention required",
            ],
            cause=cause,
        )
        self.handler_name = handler_name
        self.retry_count = retry_count

        if handler_name:
            self.details["handler_name"] = handler_name
        if retry_count > 0:
            self.details["retry_count"] = retry_count


class EventTimeoutError(EventError):
    """
    Raised when event processing times out.

    This error occurs when event delivery or handler execution
    exceeds the configured timeout.

    Attributes:
        timeout_seconds: Timeout duration

    Example:
        ```python
        async def handle_with_timeout(event: Event) -> None:
            try:
                async with timeout(30):
                    await long_running_task(event)
            except asyncio.TimeoutError as e:
                raise EventTimeoutError(
                    message="Handler timed out",
                    event_type=event.event_type,
                    timeout_seconds=30,
                    cause=e,
                )
        ```

    Raises:
        This exception when event processing times out.
    """

    def __init__(
        self,
        message: str,
        *,
        event_type: str | None = None,
        event_id: str | None = None,
        timeout_seconds: float = 0.0,
        cause: Exception | None = None,
    ) -> None:
        """
        Initialize timeout error.

        Args:
            message: Error description
            event_type: Type of event
            event_id: Event identifier
            timeout_seconds: Timeout duration
            cause: Original exception
        """
        super().__init__(
            message=message,
            event_type=event_type,
            event_id=event_id,
            severity=ErrorSeverity.MEDIUM,
            retryable=True,
            user_message="Event processing timed out.",
            suggestions=[
                "Increase timeout duration",
                "Optimize handler performance",
                "Check for deadlocks",
            ],
            cause=cause,
        )
        self.timeout_seconds = timeout_seconds
        if timeout_seconds > 0:
            self.details["timeout_seconds"] = timeout_seconds


class EventDeliveryError(EventError):
    """
    Raised when event delivery to handlers fails.

    This error occurs when the event bus cannot deliver events
    to subscribed handlers due to connection or serialization issues.

    Attributes:
        failed_handlers: List of handler names that failed

    Example:
        ```python
        try:
            await bus._deliver_to_handlers(event, handlers)
        except EventDeliveryError as e:
            logger.warning(
                f"Failed to deliver to {e.failed_handlers}",
                extra=e.to_log_dict(),
            )
        ```

    Raises:
        This exception when event delivery fails.
    """

    def __init__(
        self,
        message: str,
        *,
        event_type: str | None = None,
        event_id: str | None = None,
        failed_handlers: list[str] | None = None,
        retryable: bool = True,
        cause: Exception | None = None,
    ) -> None:
        """
        Initialize delivery error.

        Args:
            message: Error description
            event_type: Type of event
            event_id: Event identifier
            failed_handlers: Handlers that failed
            retryable: Whether operation can be retried
            cause: Original exception
        """
        super().__init__(
            message=message,
            event_type=event_type,
            event_id=event_id,
            severity=ErrorSeverity.HIGH,
            retryable=retryable,
            user_message="Failed to deliver event to handlers.",
            suggestions=[
                "Check handler availability",
                "Verify network connectivity",
                "Review handler logs",
            ],
            cause=cause,
        )
        self.failed_handlers = failed_handlers or []
        if failed_handlers:
            self.details["failed_handlers"] = failed_handlers


class EventTriggerError(EventError):
    """
    Raised when event trigger activation fails.

    This error occurs when an event trigger cannot start an agent
    or workflow in response to an event.

    Attributes:
        trigger_name: Name of the trigger
        target_type: Type of target (agent/workflow)

    Example:
        ```python
        try:
            await trigger.on_event(event)
        except EventTriggerError as e:
            logger.error(
                f"Trigger {e.trigger_name} failed",
                extra=e.to_log_dict(),
            )
        ```

    Raises:
        This exception when trigger activation fails.
    """

    def __init__(
        self,
        message: str,
        *,
        event_type: str | None = None,
        event_id: str | None = None,
        trigger_name: str | None = None,
        target_type: str | None = None,
        retryable: bool = True,
        cause: Exception | None = None,
    ) -> None:
        """
        Initialize trigger error.

        Args:
            message: Error description
            event_type: Type of event
            event_id: Event identifier
            trigger_name: Name of trigger
            target_type: Type of target (agent/workflow)
            retryable: Whether operation can be retried
            cause: Original exception
        """
        super().__init__(
            message=message,
            event_type=event_type,
            event_id=event_id,
            severity=ErrorSeverity.HIGH,
            retryable=retryable,
            user_message="Failed to activate event trigger.",
            suggestions=[
                "Verify trigger configuration",
                "Check target availability",
                "Review event mapping",
            ],
            cause=cause,
        )
        self.trigger_name = trigger_name
        self.target_type = target_type

        if trigger_name:
            self.details["trigger_name"] = trigger_name
        if target_type:
            self.details["target_type"] = target_type


class EventValidationError(EventError):
    """
    Raised when event validation fails.

    This error occurs when an event does not conform to the
    expected schema or contains invalid data.

    Attributes:
        validation_errors: List of validation error messages

    Example:
        ```python
        def validate_event(event: Event) -> None:
            errors = []
            if not event.event_type:
                errors.append("event_type is required")
            if not event.payload:
                errors.append("payload cannot be empty")

            if errors:
                raise EventValidationError(
                    message="Event validation failed",
                    validation_errors=errors,
                )
        ```

    Raises:
        This exception when event validation fails.
    """

    def __init__(
        self,
        message: str,
        *,
        event_type: str | None = None,
        event_id: str | None = None,
        validation_errors: list[str] | None = None,
        cause: Exception | None = None,
    ) -> None:
        """
        Initialize validation error.

        Args:
            message: Error description
            event_type: Type of event
            event_id: Event identifier
            validation_errors: List of validation errors
            cause: Original exception
        """
        super().__init__(
            message=message,
            event_type=event_type,
            event_id=event_id,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message="Event validation failed.",
            suggestions=[
                "Check event schema",
                "Verify required fields",
                "Review validation errors",
            ],
            cause=cause,
        )
        self.validation_errors = validation_errors or []
        if validation_errors:
            self.details["validation_errors"] = validation_errors
