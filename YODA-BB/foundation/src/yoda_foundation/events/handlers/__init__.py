"""
Event handlers for the Agentic AI Component Library.

Provides base event handler and handler registry for managing
event processing.

Example:
    ```python
    from yoda_foundation.events.handlers import (
        EventHandler,
        HandlerConfig,
        HandlerRegistry,
        HandlerBinding,
    )

    # Create custom handler
    class MyHandler(EventHandler):
        name = "my_handler"

        async def handle(
            self,
            event: Event,
            security_context: SecurityContext,
        ) -> None:
            print(f"Handling: {event.event_type}")

        async def can_handle(self, event: Event) -> bool:
            return event.event_type.startswith("my.")

    # Register handler
    registry = HandlerRegistry()
    handler_id = registry.register_handler(
        "my.*",
        MyHandler(),
        priority=10,
    )
    ```
"""

from yoda_foundation.events.handlers.async_handler import (
    AsyncEventHandler,
    AsyncHandlerConfig,
    HandlerStats,
)
from yoda_foundation.events.handlers.event_handler import (
    EventHandler,
    HandlerConfig,
)
from yoda_foundation.events.handlers.handler_registry import (
    HandlerBinding,
    HandlerRegistry,
)
from yoda_foundation.events.handlers.webhook_handler import (
    WebhookConfig,
    WebhookDeliveryResult,
    WebhookEndpoint,
    WebhookEventHandler,
    WebhookStatus,
)


__all__ = [
    # Base handler
    "EventHandler",
    "HandlerConfig",
    # Registry
    "HandlerRegistry",
    "HandlerBinding",
    # Async handler
    "AsyncEventHandler",
    "AsyncHandlerConfig",
    "HandlerStats",
    # Webhook handler
    "WebhookEventHandler",
    "WebhookConfig",
    "WebhookEndpoint",
    "WebhookDeliveryResult",
    "WebhookStatus",
]
