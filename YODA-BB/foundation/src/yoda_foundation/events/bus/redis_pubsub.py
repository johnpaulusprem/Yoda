"""
Redis pub/sub event bus implementation for distributed systems.

This module provides a Redis-backed event bus for multi-process
and distributed applications.

Example:
    ```python
    from yoda_foundation.events import RedisPubSub, RedisPubSubConfig

    # Create bus
    config = RedisPubSubConfig(
        redis_url="redis://localhost:6379",
        channel_prefix="events:",
    )
    bus = RedisPubSub(config=config)

    # Subscribe
    async def handler(event: Event) -> None:
        print(f"Received: {event.event_type}")

    sub_id = await bus.subscribe("agent.*", handler, security_context=context)

    # Publish
    event = Event(event_type="agent.completed", payload={"status": "success"})
    await bus.publish(event, security_context)

    # Cleanup
    await bus.close()
    ```
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any


try:
    import redis.asyncio as redis
    from redis.asyncio import Redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    Redis = Any  # Type hint fallback

from yoda_foundation.events.bus.event_bus import (
    Event,
    EventBus,
    EventFilter,
    EventHandler,
    EventSubscription,
)
from yoda_foundation.exceptions import (
    AgenticConnectionError,
    EventHandlerError,
    EventPublishError,
    EventSubscriptionError,
    EventTimeoutError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


@dataclass
class RedisPubSubConfig:
    """
    Configuration for Redis pub/sub event bus.

    Attributes:
        redis_url: Redis connection URL
        channel_prefix: Prefix for all event channels
        connection_pool_size: Size of connection pool
        reconnect_attempts: Number of reconnection attempts
        reconnect_delay_seconds: Delay between reconnect attempts
        message_timeout_seconds: Timeout for message delivery

    Example:
        ```python
        config = RedisPubSubConfig(
            redis_url="redis://localhost:6379/0",
            channel_prefix="myapp:events:",
            connection_pool_size=10,
        )
        ```
    """

    redis_url: str = "redis://localhost:6379/0"
    channel_prefix: str = "events:"
    connection_pool_size: int = 10
    reconnect_attempts: int = 5
    reconnect_delay_seconds: float = 1.0
    message_timeout_seconds: float = 30.0


class RedisPubSub(EventBus):
    """
    Redis pub/sub event bus implementation.

    Uses Redis pub/sub for distributed event handling across
    multiple processes and servers.

    Attributes:
        config: Bus configuration
        _redis: Redis client
        _pubsub: Redis pub/sub client
        _subscriptions: Local handler subscriptions
        _subscriber_task: Background task for receiving messages

    Example:
        ```python
        config = RedisPubSubConfig(redis_url="redis://localhost:6379")
        bus = RedisPubSub(config=config)

        # Subscribe
        async def handle_events(event: Event) -> None:
            logger.info(f"Event: {event.event_type}")

        await bus.subscribe("task.*", handle_events, security_context=context)

        # Publish
        event = Event(event_type="task.completed", payload={"id": "123"})
        await bus.publish(event, security_context)

        # Cleanup
        await bus.close()
        ```

    Raises:
        ImportError: If redis package is not installed
        EventPublishError: If publishing fails
        EventSubscriptionError: If subscription fails
    """

    def __init__(self, config: RedisPubSubConfig | None = None) -> None:
        """
        Initialize Redis pub/sub event bus.

        Args:
            config: Bus configuration

        Raises:
            ImportError: If redis is not installed
        """
        if not REDIS_AVAILABLE:
            raise ImportError(
                "redis package is required for RedisPubSub. Install it with: pip install redis"
            )

        self.config = config or RedisPubSubConfig()
        self._redis: Redis | None = None
        self._pubsub: Any | None = None
        self._subscriptions: dict[str, EventSubscription] = {}
        self._subscriber_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._connected = False

    async def _connect(self) -> None:
        """
        Connect to Redis and start subscriber.

        Raises:
            AgenticConnectionError: If connection fails
        """
        if self._connected:
            return

        try:
            # Create Redis connection pool
            self._redis = redis.from_url(
                self.config.redis_url,
                max_connections=self.config.connection_pool_size,
                decode_responses=False,
            )

            # Test connection
            await self._redis.ping()

            # Create pub/sub client
            self._pubsub = self._redis.pubsub()

            self._connected = True

            # Start subscriber task
            self._subscriber_task = asyncio.create_task(self._subscribe_loop())

            logger.info(f"Connected to Redis at {self.config.redis_url}")

        except (OSError, ConnectionError) as e:
            raise AgenticConnectionError(
                message=f"Failed to connect to Redis: {e}",
                service="redis",
                cause=e,
            )

    async def _ensure_connected(self) -> None:
        """Ensure connection is established."""
        if not self._connected:
            await self._connect()

    def _get_channel_name(self, event_type: str) -> str:
        """
        Get Redis channel name for event type.

        Args:
            event_type: Event type

        Returns:
            Channel name with prefix
        """
        return f"{self.config.channel_prefix}{event_type}"

    def _event_type_to_pattern(self, pattern: str) -> str:
        """
        Convert event type pattern to Redis pattern.

        Args:
            pattern: Event type pattern (e.g., "agent.*")

        Returns:
            Redis pattern (e.g., "events:agent.*")
        """
        # Convert "agent.*" to "events:agent.*"
        # Convert "**" to "*" (Redis doesn't have **)
        redis_pattern = pattern.replace("**", "*")
        return f"{self.config.channel_prefix}{redis_pattern}"

    async def _subscribe_loop(self) -> None:
        """
        Background task to receive and process messages.

        Continuously listens for Redis pub/sub messages and
        delivers them to matching handlers.
        """
        logger.info("Redis subscriber loop started")

        try:
            while not self._closed and self._pubsub:
                try:
                    # Get message with timeout
                    message = await self._pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )

                    if message and message["type"] == "pmessage":
                        # Deserialize event
                        try:
                            event_data = json.loads(message["data"])
                            event = Event.from_dict(event_data)

                            # Deliver to local handlers
                            await self._deliver_to_handlers(event)

                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to decode event: {e}")
                        except (ValueError, TypeError, KeyError) as e:
                            logger.error(f"Error processing message: {e}", exc_info=True)

                except TimeoutError:
                    # No message, continue
                    continue
                except (OSError, ConnectionError) as e:
                    logger.error(f"Error in subscriber loop: {e}", exc_info=True)
                    await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.info("Redis subscriber loop cancelled")
        except (OSError, ConnectionError) as e:
            logger.error(f"Redis subscriber loop failed: {e}", exc_info=True)
        finally:
            logger.info("Redis subscriber loop stopped")

    async def _deliver_to_handlers(self, event: Event) -> None:
        """
        Deliver event to matching local handlers.

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
            return

        # Sort by priority
        matching_subs.sort(key=lambda s: s.priority, reverse=True)

        logger.debug(f"Delivering event {event.event_type} to {len(matching_subs)} handlers")

        # Deliver to handlers in parallel
        tasks = [self._invoke_handler(sub, event) for sub in matching_subs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log failures
        for sub, result in zip(matching_subs, results):
            if isinstance(result, Exception):
                logger.error(
                    f"Handler {sub.subscription_id} failed: {result}",
                    exc_info=result,
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
                timeout=self.config.message_timeout_seconds,
            )
        except TimeoutError as e:
            raise EventTimeoutError(
                message=f"Handler {subscription.subscription_id} timed out",
                event_type=event.event_type,
                event_id=event.event_id,
                timeout_seconds=self.config.message_timeout_seconds,
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
        Publish an event to Redis pub/sub.

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

        await self._ensure_connected()

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
            # Serialize event
            event_data = json.dumps(event.to_dict())

            # Publish to Redis channel
            channel = self._get_channel_name(event.event_type)
            await self._redis.publish(channel, event_data)

            logger.debug(
                f"Published event {event.event_type} ({event.event_id})",
                extra={
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "channel": channel,
                },
            )

        except (OSError, ConnectionError, ValueError, TypeError) as e:
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

        await self._ensure_connected()

        if self._closed:
            raise EventSubscriptionError(
                message="Event bus is closed",
                event_type=event_type_pattern,
                reason="bus_closed",
            )

        try:
            # Create subscription
            import uuid

            subscription = EventSubscription(
                subscription_id=str(uuid.uuid4()),
                event_type_pattern=event_type_pattern,
                handler=handler,
                filters=filters or [],
                priority=priority,
                user_id=security_context.user_id,
            )

            # Subscribe to Redis pattern
            redis_pattern = self._event_type_to_pattern(event_type_pattern)
            await self._pubsub.psubscribe(redis_pattern)

            # Store local subscription
            async with self._lock:
                self._subscriptions[subscription.subscription_id] = subscription

            logger.info(
                f"Subscribed to {event_type_pattern} ({subscription.subscription_id})",
                extra={
                    "event_type_pattern": event_type_pattern,
                    "subscription_id": subscription.subscription_id,
                    "redis_pattern": redis_pattern,
                },
            )

            return subscription.subscription_id

        except (OSError, ConnectionError) as e:
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
                    subscription = self._subscriptions[subscription_id]

                    # Unsubscribe from Redis pattern
                    redis_pattern = self._event_type_to_pattern(subscription.event_type_pattern)
                    await self._pubsub.punsubscribe(redis_pattern)

                    # Remove local subscription
                    del self._subscriptions[subscription_id]

                    logger.info(f"Unsubscribed: {subscription_id}")
                else:
                    logger.warning(f"Subscription not found: {subscription_id}")

        except (OSError, ConnectionError) as e:
            raise EventSubscriptionError(
                message=f"Failed to unsubscribe: {e}",
                subscription_id=subscription_id,
                cause=e,
            )

    async def close(self) -> None:
        """
        Close the event bus and cleanup resources.

        Example:
            ```python
            await bus.close()
            ```
        """
        logger.info("Closing Redis event bus")

        self._closed = True

        # Cancel subscriber task
        if self._subscriber_task and not self._subscriber_task.done():
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass

        # Close pub/sub
        if self._pubsub:
            try:
                await self._pubsub.close()
            except (OSError, ConnectionError) as e:
                logger.error(f"Error closing pub/sub: {e}")

        # Close Redis connection
        if self._redis:
            try:
                await self._redis.close()
            except (OSError, ConnectionError) as e:
                logger.error(f"Error closing Redis: {e}")

        # Clear subscriptions
        async with self._lock:
            self._subscriptions.clear()

        self._connected = False

        logger.info("Redis event bus closed")

    async def __aenter__(self) -> RedisPubSub:
        """Context manager entry."""
        await self._ensure_connected()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        await self.close()
