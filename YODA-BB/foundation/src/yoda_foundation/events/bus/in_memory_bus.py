"""
In-memory event bus implementation for development and testing.

This module provides a thread-safe in-memory event bus suitable for
single-process applications, development, and testing.

Example:
    ```python
    from yoda_foundation.events import InMemoryBus, Event

    # Create bus
    bus = InMemoryBus(
        config=InMemoryConfig(
            max_queue_size=10000,
            delivery_timeout_seconds=30.0,
        )
    )

    # Subscribe
    async def handler(event: Event) -> None:
        print(f"Received: {event.event_type}")

    sub_id = await bus.subscribe("agent.*", handler, security_context=context)

    # Publish
    event = Event(event_type="agent.completed", payload={"status": "success"})
    await bus.publish(event, security_context)
    ```
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from yoda_foundation.events.bus.event_bus import (
    Event,
    EventBus,
    EventFilter,
    EventHandler,
    EventSubscription,
)
from yoda_foundation.exceptions import (
    EventDeliveryError,
    EventHandlerError,
    EventPublishError,
    EventSubscriptionError,
    EventTimeoutError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


@dataclass
class InMemoryConfig:
    """
    Configuration for in-memory event bus.

    Attributes:
        max_queue_size: Maximum events in queue
        delivery_timeout_seconds: Timeout for handler execution
        enable_replay: Whether to store events for replay
        replay_buffer_size: Number of events to keep for replay
        parallel_delivery: Whether to deliver to handlers in parallel

    Example:
        ```python
        config = InMemoryConfig(
            max_queue_size=5000,
            delivery_timeout_seconds=60.0,
            enable_replay=True,
            replay_buffer_size=1000,
        )
        ```
    """

    max_queue_size: int = 10000
    delivery_timeout_seconds: float = 30.0
    enable_replay: bool = False
    replay_buffer_size: int = 1000
    parallel_delivery: bool = True


class InMemoryBus(EventBus):
    """
    In-memory event bus implementation.

    Thread-safe event bus using asyncio for event delivery.
    Suitable for single-process applications and testing.

    Attributes:
        config: Bus configuration
        _subscriptions: Registered subscriptions
        _event_queue: Queue of events to process
        _replay_buffer: Buffer of recent events for replay
        _processing_task: Background task processing events

    Example:
        ```python
        bus = InMemoryBus()

        # Subscribe to events
        async def log_events(event: Event) -> None:
            logger.info(f"Event: {event.event_type}")

        await bus.subscribe("**", log_events, security_context=context)

        # Publish events
        event = Event(event_type="user.created", payload={"user_id": "123"})
        await bus.publish(event, security_context)

        # Cleanup
        await bus.close()
        ```

    Raises:
        EventPublishError: If publishing fails
        EventSubscriptionError: If subscription fails
    """

    def __init__(self, config: InMemoryConfig | None = None) -> None:
        """
        Initialize in-memory event bus.

        Args:
            config: Bus configuration
        """
        self.config = config or InMemoryConfig()
        self._subscriptions: dict[str, EventSubscription] = {}
        self._event_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self.config.max_queue_size)
        self._replay_buffer: list[Event] = []
        self._processing_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._closed = False

        # Start background processing
        self._start_processing()

    def _start_processing(self) -> None:
        """Start background event processing task."""
        if self._processing_task is None or self._processing_task.done():
            self._processing_task = asyncio.create_task(self._process_events())

    async def _process_events(self) -> None:
        """
        Background task to process events from queue.

        Continuously processes events and delivers to matching handlers.
        """
        logger.info("Event bus processing started")

        try:
            while not self._closed:
                try:
                    # Get event from queue with timeout
                    event = await asyncio.wait_for(
                        self._event_queue.get(),
                        timeout=1.0,
                    )

                    # Deliver to handlers
                    await self._deliver_event(event)

                    # Add to replay buffer if enabled
                    if self.config.enable_replay:
                        async with self._lock:
                            self._replay_buffer.append(event)
                            # Trim buffer if needed
                            if len(self._replay_buffer) > self.config.replay_buffer_size:
                                self._replay_buffer.pop(0)

                    self._event_queue.task_done()

                except TimeoutError:
                    # No events in queue, continue
                    continue
                except (EventDeliveryError, ValueError, TypeError) as e:
                    logger.error(f"Error processing event: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Event bus processing cancelled")
        except (EventDeliveryError, OSError) as e:
            logger.error(f"Event bus processing failed: {e}", exc_info=True)
        finally:
            logger.info("Event bus processing stopped")

    async def _deliver_event(self, event: Event) -> None:
        """
        Deliver event to matching handlers.

        Args:
            event: Event to deliver
        """
        # Get matching subscriptions
        matching_subs = []
        async with self._lock:
            for sub in self._subscriptions.values():
                if sub.should_handle(event):
                    matching_subs.append(sub)

        if not matching_subs:
            logger.debug(f"No handlers for event: {event.event_type}")
            return

        # Sort by priority (higher first)
        matching_subs.sort(key=lambda s: s.priority, reverse=True)

        logger.debug(f"Delivering event {event.event_type} to {len(matching_subs)} handlers")

        # Deliver to handlers
        failed_handlers = []

        if self.config.parallel_delivery:
            # Deliver in parallel
            tasks = [self._invoke_handler(sub, event) for sub in matching_subs]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Check for failures
            for sub, result in zip(matching_subs, results):
                if isinstance(result, Exception):
                    failed_handlers.append(sub.subscription_id)
                    logger.error(
                        f"Handler {sub.subscription_id} failed: {result}",
                        exc_info=result,
                    )
        else:
            # Deliver sequentially
            for sub in matching_subs:
                try:
                    await self._invoke_handler(sub, event)
                except (EventHandlerError, EventTimeoutError, ValueError, TypeError) as e:
                    failed_handlers.append(sub.subscription_id)
                    logger.error(
                        f"Handler {sub.subscription_id} failed: {e}",
                        exc_info=True,
                    )

        if failed_handlers:
            logger.warning(
                f"Event {event.event_id} delivery failed for {len(failed_handlers)} handlers"
            )

    async def _invoke_handler(
        self,
        subscription: EventSubscription,
        event: Event,
    ) -> None:
        """
        Invoke a single handler with timeout.

        Args:
            subscription: Subscription with handler
            event: Event to handle

        Raises:
            EventHandlerError: If handler fails
            EventTimeoutError: If handler times out
        """
        try:
            await asyncio.wait_for(
                subscription.handler(event),
                timeout=self.config.delivery_timeout_seconds,
            )
        except TimeoutError as e:
            raise EventTimeoutError(
                message=f"Handler {subscription.subscription_id} timed out",
                event_type=event.event_type,
                event_id=event.event_id,
                timeout_seconds=self.config.delivery_timeout_seconds,
                cause=e,
            )
        except (ValueError, TypeError, KeyError) as e:
            raise EventHandlerError(
                message=f"Handler {subscription.subscription_id} failed",
                event_type=event.event_type,
                event_id=event.event_id,
                handler_name=subscription.subscription_id,
                retryable=False,
                cause=e,
            )

    async def publish(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Publish an event to the bus.

        Args:
            event: Event to publish
            security_context: Security context for authorization

        Raises:
            EventPublishError: If publication fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            event = Event(
                event_type="document.processed",
                payload={"doc_id": "123"},
            )
            await bus.publish(event, security_context)
            ```
        """
        # Check permission
        security_context.require_permission("event.publish")

        if self._closed:
            raise EventPublishError(
                message="Event bus is closed",
                event_type=event.event_type,
                event_id=event.event_id,
                retryable=False,
            )

        # Set source if not already set
        if event.source is None:
            event.source = security_context.user_id

        # Set correlation ID from context if not set
        if event.correlation_id is None and security_context.correlation_id:
            event.correlation_id = security_context.correlation_id

        try:
            # Add to queue (non-blocking with timeout)
            await asyncio.wait_for(
                self._event_queue.put(event),
                timeout=1.0,
            )

            logger.debug(
                f"Published event {event.event_type} ({event.event_id})",
                extra={
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "user_id": security_context.user_id,
                },
            )

        except TimeoutError as e:
            raise EventPublishError(
                message="Event queue is full",
                event_type=event.event_type,
                event_id=event.event_id,
                reason="queue_full",
                retryable=True,
                cause=e,
            )
        except (ValueError, TypeError) as e:
            raise EventPublishError(
                message=f"Failed to publish event: {e}",
                event_type=event.event_type,
                event_id=event.event_id,
                retryable=True,
                cause=e,
            )

    async def subscribe(
        self,
        event_type_pattern: str,
        handler: EventHandler,
        security_context: SecurityContext,
        filters: list[EventFilter] | None = None,
        priority: int = 0,
    ) -> str:
        """
        Subscribe to events matching a pattern.

        Args:
            event_type_pattern: Pattern to match (supports wildcards)
            handler: Async handler function
            security_context: Security context for authorization
            filters: Additional event filters
            priority: Handler priority (higher = earlier execution)

        Returns:
            Subscription ID for later unsubscribe

        Raises:
            EventSubscriptionError: If subscription fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            async def my_handler(event: Event) -> None:
                print(f"Got: {event.event_type}")

            sub_id = await bus.subscribe(
                "agent.*",
                my_handler,
                security_context=context,
                priority=10,
            )
            ```
        """
        # Check permission
        security_context.require_permission("event.subscribe")

        if self._closed:
            raise EventSubscriptionError(
                message="Event bus is closed",
                event_type=event_type_pattern,
                reason="bus_closed",
            )

        try:
            subscription = EventSubscription(
                subscription_id=str(asyncio.current_task()),
                event_type_pattern=event_type_pattern,
                handler=handler,
                filters=filters or [],
                priority=priority,
                user_id=security_context.user_id,
            )

            async with self._lock:
                self._subscriptions[subscription.subscription_id] = subscription

            logger.info(
                f"Subscribed to {event_type_pattern} ({subscription.subscription_id})",
                extra={
                    "event_type_pattern": event_type_pattern,
                    "subscription_id": subscription.subscription_id,
                    "priority": priority,
                },
            )

            return subscription.subscription_id

        except (ValueError, TypeError) as e:
            raise EventSubscriptionError(
                message=f"Failed to subscribe: {e}",
                event_type=event_type_pattern,
                cause=e,
            )

    async def unsubscribe(
        self,
        subscription_id: str,
        security_context: SecurityContext,
    ) -> None:
        """
        Remove a subscription.

        Args:
            subscription_id: ID returned from subscribe()
            security_context: Security context for authorization

        Raises:
            EventSubscriptionError: If unsubscribe fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            await bus.unsubscribe(sub_id, security_context)
            ```
        """
        # Check permission
        security_context.require_permission("event.unsubscribe")

        try:
            async with self._lock:
                if subscription_id in self._subscriptions:
                    del self._subscriptions[subscription_id]
                    logger.info(f"Unsubscribed: {subscription_id}")
                else:
                    logger.warning(f"Subscription not found: {subscription_id}")

        except (ValueError, TypeError, KeyError) as e:
            raise EventSubscriptionError(
                message=f"Failed to unsubscribe: {e}",
                subscription_id=subscription_id,
                cause=e,
            )

    async def get_replay_events(
        self,
        event_type_pattern: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Event]:
        """
        Get events from replay buffer.

        Args:
            event_type_pattern: Filter by event type pattern
            since: Only events after this timestamp
            limit: Maximum number of events to return

        Returns:
            List of events matching criteria

        Example:
            ```python
            # Get last 100 agent events
            events = await bus.get_replay_events(
                event_type_pattern="agent.*",
                limit=100,
            )
            ```
        """
        if not self.config.enable_replay:
            return []

        async with self._lock:
            events = self._replay_buffer.copy()

        # Filter by pattern
        if event_type_pattern:
            events = [e for e in events if e.matches_pattern(event_type_pattern)]

        # Filter by timestamp
        if since:
            events = [e for e in events if e.timestamp >= since]

        # Apply limit
        if limit:
            events = events[-limit:]

        return events

    async def close(self) -> None:
        """
        Close the event bus and cleanup resources.

        Example:
            ```python
            await bus.close()
            ```
        """
        logger.info("Closing event bus")

        self._closed = True

        # Cancel processing task
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

        # Clear subscriptions
        async with self._lock:
            self._subscriptions.clear()

        logger.info("Event bus closed")

    async def __aenter__(self) -> InMemoryBus:
        """Context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        await self.close()
