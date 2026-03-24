"""
Events module for the Agentic AI Component Library.

Provides event-driven architecture components including event bus,
handlers, triggers, and cross-pillar event schemas for building
reactive systems.

Example:
    ```python
    from yoda_foundation.events import (
        # Event bus
        Event,
        EventBus,
        InMemoryBus,
        RedisPubSub,
        # Handlers
        EventHandler,
        HandlerRegistry,
        # Triggers
        AgentTrigger,
        WorkflowTrigger,
        # Pillar events
        PillarType,
        PillarEventType,
        BasePillarEvent,
        CrossPillarEvent,
        PillarEventHandler,
        create_policy_event,
        create_lifecycle_event,
        # Security
        SecurityContext,
        create_security_context,
    )

    # Create event bus
    bus = InMemoryBus()

    # Create handler
    class MyHandler(EventHandler):
        name = "my_handler"

        async def handle(self, event: Event, security_context: SecurityContext) -> None:
            print(f"Handling: {event.event_type}")

        async def can_handle(self, event: Event) -> bool:
            return True

    # Register handler
    registry = HandlerRegistry()
    registry.register_handler("my.*", MyHandler())

    # Subscribe to events
    async def handle_event(event: Event) -> None:
        handlers = registry.get_handlers_for_event(event)
        for handler in handlers:
            if await handler.can_handle(event):
                await handler.handle(event, security_context)

    sub_id = await bus.subscribe("my.*", handle_event, security_context=context)

    # Publish event
    event = Event(event_type="my.event", payload={"data": "test"})
    await bus.publish(event, security_context)

    # Create cross-pillar event
    pillar_event = CrossPillarEvent.create(
        event_type=PillarEventType.POLICY_EVALUATED,
        target_pillar=PillarType.AGENT_LIFECYCLE,
        payload={"policy_id": "pol_123", "decision": "allow"},
    )

    # Cleanup
    await bus.close()
    ```
"""

from yoda_foundation.events.bus import (
    # Core types
    Event,
    EventBus,
    EventFilter,
    EventPriority,
    # Router
    EventRouter,
    EventSubscription,
    FilterOperator,
    # In-memory implementation
    InMemoryBus,
    InMemoryConfig,
    # Redis implementation
    RedisPubSub,
    RedisPubSubConfig,
    Route,
    RouteConfig,
)
from yoda_foundation.events.bus import (
    EventHandler as EventHandlerFunc,
)
from yoda_foundation.events.handlers import (
    # Async handler
    AsyncEventHandler,
    AsyncHandlerConfig,
    # Base handler
    EventHandler,
    HandlerBinding,
    HandlerConfig,
    # Registry
    HandlerRegistry,
    HandlerStats,
    WebhookConfig,
    WebhookDeliveryResult,
    WebhookEndpoint,
    # Webhook handler
    WebhookEventHandler,
    WebhookStatus,
)
from yoda_foundation.events.monitoring import (
    EventMetrics,
    MetricsConfig,
    MetricsSummary,
    MetricType,
)
from yoda_foundation.events.schemas import (
    AgentEvent,
    AgentEventType,
    BaseEvent,
    EventSeverity,
    LLMEvent,
    LLMEventType,
    RAGEvent,
    RAGEventType,
    SecurityEvent,
    SecurityEventType,
    SystemEvent,
    SystemEventType,
    ToolEvent,
    ToolEventType,
)
from yoda_foundation.events.streaming import (
    AggregationConfig,
    AggregationResult,
    BackpressureStrategy,
    DetectedPattern,
    # Event Aggregator
    EventAggregator,
    # Event Stream
    EventStream,
    PatternConfig,
    PatternDetector,
    StreamConfig,
    StreamStats,
    WindowType,
)
from yoda_foundation.events.streaming import (
    AggregationType as StreamAggregationType,
)
from yoda_foundation.events.triggers import (
    AggregationType,
    Condition,
    ConditionalTrigger,
    ConditionalTriggerConfig,
    ConditionOperator,
    ScheduledTrigger,
    ScheduledTriggerConfig,
    ScheduleType,
    WorkflowTrigger,
    WorkflowTriggerConfig,
)


__all__ = [
    # Event bus - Core types
    "Event",
    "EventBus",
    "EventHandlerFunc",
    "EventSubscription",
    "EventFilter",
    "EventPriority",
    # Event bus - In-memory
    "InMemoryBus",
    "InMemoryConfig",
    # Event bus - Redis
    "RedisPubSub",
    "RedisPubSubConfig",
    # Event bus - Router
    "EventRouter",
    "Route",
    "RouteConfig",
    "FilterOperator",
    # Handlers - Base
    "EventHandler",
    "HandlerConfig",
    "HandlerRegistry",
    "HandlerBinding",
    # Handlers - Async
    "AsyncEventHandler",
    "AsyncHandlerConfig",
    "HandlerStats",
    # Handlers - Webhook
    "WebhookEventHandler",
    "WebhookConfig",
    "WebhookEndpoint",
    "WebhookDeliveryResult",
    "WebhookStatus",
    # Triggers - Workflow
    "WorkflowTrigger",
    "WorkflowTriggerConfig",
    # Triggers - Scheduled
    "ScheduledTrigger",
    "ScheduledTriggerConfig",
    "ScheduleType",
    # Triggers - Conditional
    "ConditionalTrigger",
    "ConditionalTriggerConfig",
    "Condition",
    "ConditionOperator",
    "AggregationType",
    # Event Severity
    "EventSeverity",
    # Component Event Types
    "AgentEventType",
    "ToolEventType",
    "LLMEventType",
    "RAGEventType",
    "SecurityEventType",
    "SystemEventType",
    # Component Events
    "BaseEvent",
    "AgentEvent",
    "ToolEvent",
    "LLMEvent",
    "RAGEvent",
    "SecurityEvent",
    "SystemEvent",
    # Streaming - Event Stream
    "EventStream",
    "StreamConfig",
    "BackpressureStrategy",
    "StreamStats",
    # Streaming - Aggregator
    "EventAggregator",
    "AggregationConfig",
    "WindowType",
    "StreamAggregationType",
    "AggregationResult",
    "PatternDetector",
    "PatternConfig",
    "DetectedPattern",
    # Monitoring
    "EventMetrics",
    "MetricsConfig",
    "MetricType",
    "MetricsSummary",
]
