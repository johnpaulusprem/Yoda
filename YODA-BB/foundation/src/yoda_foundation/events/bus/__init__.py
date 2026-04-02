"""
Event bus implementations for the Agentic AI Component Library.

Provides both in-memory and distributed (Redis) event bus implementations.

Example:
    ```python
    from yoda_foundation.events.bus import (
        Event,
        EventBus,
        EventFilter,
        EventPriority,
        InMemoryBus,
        InMemoryConfig,
        RedisPubSub,
        RedisPubSubConfig,
    )

    # Use in-memory bus for development
    bus = InMemoryBus()

    # Or use Redis for production
    config = RedisPubSubConfig(redis_url="redis://localhost:6379")
    bus = RedisPubSub(config=config)
    ```
"""

from yoda_foundation.events.bus.event_bus import (
    Event,
    EventBus,
    EventFilter,
    EventHandler,
    EventPriority,
    EventSubscription,
)
from yoda_foundation.events.bus.event_router import (
    EventFilter as RouterEventFilter,
)
from yoda_foundation.events.bus.event_router import (
    EventRouter,
    FilterOperator,
    Route,
    RouteConfig,
    RouteHandler,
)
from yoda_foundation.events.bus.in_memory_bus import (
    InMemoryBus,
    InMemoryConfig,
)
from yoda_foundation.events.bus.redis_pubsub import (
    RedisPubSub,
    RedisPubSubConfig,
)


__all__ = [
    # Core types
    "Event",
    "EventBus",
    "EventHandler",
    "EventSubscription",
    "EventFilter",
    "EventPriority",
    # In-memory implementation
    "InMemoryBus",
    "InMemoryConfig",
    # Redis implementation
    "RedisPubSub",
    "RedisPubSubConfig",
    # Router
    "EventRouter",
    "Route",
    "RouteConfig",
    "RouterEventFilter",
    "FilterOperator",
    "RouteHandler",
]
