"""
Event bus interface and core event types for the Agentic AI Component Library.

This module provides the abstract event bus interface and event types
for building event-driven architectures.

Example:
    ```python
    from yoda_foundation.events import Event, EventBus, create_security_context

    # Define event
    event = Event(
        event_type="agent.completed",
        payload={"agent_id": "agent_123", "result": "success"},
        metadata={"priority": "high"},
    )

    # Publish event
    bus = get_event_bus()
    await bus.publish(event, security_context)

    # Subscribe to events
    async def handle_agent_events(event: Event) -> None:
        print(f"Agent event: {event.payload}")

    subscription_id = await bus.subscribe(
        "agent.*",
        handle_agent_events,
        security_context=security_context,
    )
    ```
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from yoda_foundation.security import SecurityContext


class EventPriority(Enum):
    """Priority level for event delivery."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Event:
    """
    Base event class for the event bus.

    All events in the system inherit from or use this class.
    Events are immutable once created.

    Attributes:
        event_type: Type/category of the event (e.g., "agent.completed")
        payload: Event data payload
        metadata: Additional event metadata
        event_id: Unique event identifier
        timestamp: When the event was created
        source: Source of the event (service/agent name)
        correlation_id: Correlation ID for tracing
        priority: Event priority for delivery

    Example:
        ```python
        event = Event(
            event_type="document.processed",
            payload={
                "document_id": "doc_123",
                "status": "completed",
            },
            metadata={"processing_time_ms": 1234},
            source="document_processor",
        )
        ```
    """

    event_type: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    source: str | None = None
    correlation_id: str | None = None
    priority: EventPriority = EventPriority.NORMAL

    def to_dict(self) -> dict[str, Any]:
        """
        Convert event to dictionary for serialization.

        Returns:
            Dictionary representation of the event

        Example:
            ```python
            event_dict = event.to_dict()
            await redis.publish("events", json.dumps(event_dict))
            ```
        """
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "correlation_id": self.correlation_id,
            "priority": self.priority.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        """
        Create event from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            Event instance

        Example:
            ```python
            data = json.loads(message)
            event = Event.from_dict(data)
            ```
        """
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now(UTC)

        priority = EventPriority(data.get("priority", "normal"))

        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            event_type=data["event_type"],
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
            timestamp=timestamp,
            source=data.get("source"),
            correlation_id=data.get("correlation_id"),
            priority=priority,
        )

    def matches_pattern(self, pattern: str) -> bool:
        """
        Check if event type matches a pattern.

        Supports wildcards:
        - "*" matches any single segment
        - "**" matches any number of segments

        Args:
            pattern: Pattern to match (e.g., "agent.*", "document.**")

        Returns:
            True if event type matches pattern

        Example:
            ```python
            event = Event(event_type="agent.completed", payload={})
            assert event.matches_pattern("agent.*")
            assert event.matches_pattern("agent.completed")
            assert not event.matches_pattern("tool.*")
            ```
        """
        if pattern == self.event_type:
            return True

        # Split into segments
        pattern_parts = pattern.split(".")
        type_parts = self.event_type.split(".")

        # Handle ** wildcard (matches any number of segments)
        if "**" in pattern_parts:
            idx = pattern_parts.index("**")
            # Check prefix
            if idx > 0:
                if pattern_parts[:idx] != type_parts[:idx]:
                    return False
            # Check suffix
            suffix_pattern = pattern_parts[idx + 1 :]
            if suffix_pattern:
                if len(type_parts) < len(suffix_pattern):
                    return False
                if type_parts[-len(suffix_pattern) :] != suffix_pattern:
                    return False
            return True

        # Handle * wildcard (matches single segment)
        if len(pattern_parts) != len(type_parts):
            return False

        for pattern_part, type_part in zip(pattern_parts, type_parts):
            if pattern_part != "*" and pattern_part != type_part:
                return False

        return True


# Type alias for event handlers
EventHandler = Callable[[Event], Awaitable[None]]


@dataclass
class EventFilter:
    """
    Filter for event subscriptions.

    Allows filtering events based on payload or metadata values.

    Attributes:
        field_path: Dot-separated path to field (e.g., "payload.status")
        operator: Filter operator ("eq", "ne", "in", "contains")
        value: Value to compare against

    Example:
        ```python
        # Only receive events where payload.status == "completed"
        filter = EventFilter(
            field_path="payload.status",
            operator="eq",
            value="completed",
        )

        subscription_id = await bus.subscribe(
            "document.*",
            handler,
            filters=[filter],
            security_context=context,
        )
        ```
    """

    field_path: str
    operator: str  # "eq", "ne", "in", "contains", "gt", "lt"
    value: Any

    def matches(self, event: Event) -> bool:
        """
        Check if event matches this filter.

        Args:
            event: Event to check

        Returns:
            True if event matches filter
        """
        # Navigate field path
        obj = event.to_dict()
        for part in self.field_path.split("."):
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            else:
                return False

        # Apply operator
        if self.operator == "eq":
            return obj == self.value
        elif self.operator == "ne":
            return obj != self.value
        elif self.operator == "in":
            return obj in self.value if isinstance(self.value, (list, set, tuple)) else False
        elif self.operator == "contains":
            return self.value in obj if isinstance(obj, (list, set, tuple, str)) else False
        elif self.operator == "gt":
            return obj > self.value
        elif self.operator == "lt":
            return obj < self.value
        else:
            return False


@dataclass
class EventSubscription:
    """
    Subscription to events on the event bus.

    Represents a handler registered to receive events matching a pattern.

    Attributes:
        subscription_id: Unique subscription identifier
        event_type_pattern: Event type pattern to match
        handler: Async function to handle events
        filters: Additional filters for events
        priority: Handler priority (higher runs first)
        created_at: When subscription was created
        user_id: User who created the subscription

    Example:
        ```python
        async def my_handler(event: Event) -> None:
            print(f"Received: {event.event_type}")

        subscription = EventSubscription(
            subscription_id="sub_123",
            event_type_pattern="agent.*",
            handler=my_handler,
            priority=10,
        )
        ```
    """

    subscription_id: str
    event_type_pattern: str
    handler: EventHandler
    filters: list[EventFilter] = field(default_factory=list)
    priority: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    user_id: str | None = None

    def should_handle(self, event: Event) -> bool:
        """
        Check if this subscription should handle the event.

        Args:
            event: Event to check

        Returns:
            True if handler should be invoked
        """
        # Check type pattern
        if not event.matches_pattern(self.event_type_pattern):
            return False

        # Check additional filters
        for filter in self.filters:
            if not filter.matches(event):
                return False

        return True


class EventBus(ABC):
    """
    Abstract event bus interface.

    Defines the contract for event bus implementations.
    Implementations can be in-memory, Redis-based, Kafka-based, etc.

    Example:
        ```python
        class MyEventBus(EventBus):
            async def publish(
                self,
                event: Event,
                security_context: SecurityContext,
            ) -> None:
                # Implementation
                pass

            async def subscribe(
                self,
                event_type_pattern: str,
                handler: EventHandler,
                security_context: SecurityContext,
                filters: Optional[List[EventFilter]] = None,
                priority: int = 0,
            ) -> str:
                # Implementation
                pass
        ```
    """

    @abstractmethod
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
                event_type="task.completed",
                payload={"task_id": "task_123"},
            )
            await bus.publish(event, security_context)
            ```
        """
        pass

    @abstractmethod
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
            async def handle_events(event: Event) -> None:
                print(f"Got event: {event.event_type}")

            sub_id = await bus.subscribe(
                "agent.*",
                handle_events,
                security_context=context,
                priority=10,
            )
            ```
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def close(self) -> None:
        """
        Close the event bus and cleanup resources.

        Example:
            ```python
            await bus.close()
            ```
        """
        pass
