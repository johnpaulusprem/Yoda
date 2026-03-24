"""
Base event handler for the Agentic AI Component Library.

This module provides the abstract event handler interface and
configuration for processing events.

Example:
    ```python
    from yoda_foundation.events import EventHandler, HandlerConfig, Event

    class DocumentHandler(EventHandler):
        name = "document_handler"

        async def handle(
            self,
            event: Event,
            security_context: SecurityContext,
        ) -> None:
            doc_id = event.payload.get("document_id")
            print(f"Processing document: {doc_id}")

        async def can_handle(self, event: Event) -> bool:
            return "document_id" in event.payload

    # Use handler
    handler = DocumentHandler()
    if await handler.can_handle(event):
        await handler.handle(event, security_context)
    ```
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from yoda_foundation.events.bus.event_bus import Event
from yoda_foundation.exceptions import (
    EventHandlerError,
    EventTimeoutError,
    ValidationError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


@dataclass
class HandlerConfig:
    """
    Configuration for event handlers.

    Attributes:
        max_retries: Maximum retry attempts on failure
        retry_delay_seconds: Delay between retries
        timeout_seconds: Handler execution timeout
        continue_on_error: Whether to continue processing on error
        log_errors: Whether to log errors

    Example:
        ```python
        config = HandlerConfig(
            max_retries=3,
            retry_delay_seconds=1.0,
            timeout_seconds=30.0,
            continue_on_error=True,
        )

        handler = MyHandler(config=config)
        ```
    """

    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    timeout_seconds: float = 30.0
    continue_on_error: bool = True
    log_errors: bool = True

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.max_retries < 0:
            raise ValidationError(
                message=f"max_retries cannot be negative, got {self.max_retries}",
                field_name="max_retries",
            )
        if self.retry_delay_seconds < 0:
            raise ValidationError(
                message=f"retry_delay_seconds cannot be negative, got {self.retry_delay_seconds}",
                field_name="retry_delay_seconds",
            )
        if self.timeout_seconds <= 0:
            raise ValidationError(
                message=f"timeout_seconds must be positive, got {self.timeout_seconds}",
                field_name="timeout_seconds",
            )


class EventHandler(ABC):
    """
    Abstract base class for event handlers.

    All event handlers should inherit from this class and implement
    the handle() and can_handle() methods.

    Attributes:
        name: Handler name/identifier
        config: Handler configuration

    Example:
        ```python
        class NotificationHandler(EventHandler):
            name = "notification_handler"

            async def handle(
                self,
                event: Event,
                security_context: SecurityContext,
            ) -> None:
                # Send notification
                await send_email(event.payload)

            async def can_handle(self, event: Event) -> bool:
                # Check if event requires notification
                return event.event_type.startswith("user.")

        # Register with event bus
        handler = NotificationHandler()
        await bus.subscribe(
            "user.*",
            lambda e: handler.handle(e, security_context),
            security_context=context,
        )
        ```

    Raises:
        EventHandlerError: If handler execution fails
    """

    name: str = "base_handler"

    def __init__(self, config: HandlerConfig | None = None) -> None:
        """
        Initialize event handler.

        Args:
            config: Handler configuration
        """
        self.config = config or HandlerConfig()
        self._logger = logging.getLogger(f"{__name__}.{self.name}")

    @abstractmethod
    async def handle(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Handle an event.

        This method should process the event and perform the necessary
        actions. It should be idempotent where possible.

        Args:
            event: Event to handle
            security_context: Security context for authorization

        Raises:
            EventHandlerError: If handling fails
            EventTimeoutError: If handling times out
            AuthorizationError: If user lacks permission

        Example:
            ```python
            async def handle(
                self,
                event: Event,
                security_context: SecurityContext,
            ) -> None:
                # Check permission
                security_context.require_permission("document.process")

                # Process event
                doc_id = event.payload["document_id"]
                await self.process_document(doc_id)
            ```
        """
        pass

    @abstractmethod
    async def can_handle(self, event: Event) -> bool:
        """
        Check if this handler can process the event.

        This method should perform quick checks to determine if
        the handler is applicable for the event.

        Args:
            event: Event to check

        Returns:
            True if handler can process the event

        Example:
            ```python
            async def can_handle(self, event: Event) -> bool:
                # Check event type and payload structure
                return (
                    event.event_type == "document.uploaded"
                    and "document_id" in event.payload
                    and "user_id" in event.payload
                )
            ```
        """
        pass

    async def handle_with_retry(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Handle event with automatic retry on failure.

        Args:
            event: Event to handle
            security_context: Security context

        Raises:
            EventHandlerError: If all retries fail
        """
        import asyncio

        last_error = None
        retry_count = 0

        while retry_count <= self.config.max_retries:
            try:
                # Execute handler with timeout
                await asyncio.wait_for(
                    self.handle(event, security_context),
                    timeout=self.config.timeout_seconds,
                )

                # Success
                if retry_count > 0:
                    self._logger.info(
                        f"Handler succeeded after {retry_count} retries",
                        extra={
                            "event_type": event.event_type,
                            "event_id": event.event_id,
                            "retry_count": retry_count,
                        },
                    )
                return

            except TimeoutError as e:
                last_error = EventTimeoutError(
                    message=f"Handler {self.name} timed out",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    timeout_seconds=self.config.timeout_seconds,
                    cause=e,
                )

            except EventHandlerError as e:
                last_error = e

            except (ValueError, TypeError, KeyError) as e:
                last_error = EventHandlerError(
                    message=f"Handler {self.name} failed: {e}",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    handler_name=self.name,
                    retry_count=retry_count,
                    retryable=retry_count < self.config.max_retries,
                    cause=e,
                )

            # Check if we should retry
            if not last_error.retryable or retry_count >= self.config.max_retries:
                break

            # Log retry attempt
            retry_count += 1
            self._logger.warning(
                f"Handler failed, retrying ({retry_count}/{self.config.max_retries})",
                extra={
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "error": str(last_error),
                },
            )

            # Wait before retry
            await asyncio.sleep(self.config.retry_delay_seconds)

        # All retries exhausted
        if self.config.log_errors:
            self._logger.error(
                f"Handler failed after {retry_count} retries",
                extra=last_error.to_log_dict() if last_error else {},
            )

        if not self.config.continue_on_error:
            raise last_error

    async def on_error(
        self,
        event: Event,
        error: Exception,
    ) -> None:
        """
        Hook called when handler fails.

        Override this method to implement custom error handling
        like dead letter queues, notifications, etc.

        Args:
            event: Event that failed
            error: Exception that occurred

        Example:
            ```python
            async def on_error(
                self,
                event: Event,
                error: Exception,
            ) -> None:
                # Send to dead letter queue
                await self.dlq.publish({
                    "event": event.to_dict(),
                    "error": str(error),
                    "handler": self.name,
                })

                # Send alert
                await self.alerts.send(
                    f"Handler {self.name} failed: {error}"
                )
            ```
        """
        if self.config.log_errors:
            self._logger.error(
                f"Handler error for event {event.event_id}",
                exc_info=error,
            )

    def __str__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}({self.name})"

    def __repr__(self) -> str:
        """Detailed representation."""
        return f"{self.__class__.__name__}(name={self.name!r}, config={self.config!r})"
