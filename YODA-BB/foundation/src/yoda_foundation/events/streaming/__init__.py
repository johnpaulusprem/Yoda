"""
Event streaming module for the Agentic AI Component Library.

Provides real-time event streaming capabilities with backpressure
handling, filtering, and aggregation.

Example:
    ```python
    from yoda_foundation.events.streaming import (
        EventStream,
        EventAggregator,
        StreamConfig,
        AggregationConfig,
        WindowType,
    )

    # Create event stream
    stream = EventStream(
        config=StreamConfig(
            buffer_size=1000,
            backpressure_strategy="drop_oldest",
        ),
    )

    # Subscribe to events
    async for event in stream.iterate(security_context=context):
        await process(event)

    # Filtered stream
    async for event in stream.filter(
        lambda e: e.event_type.startswith("agent."),
        security_context=context,
    ):
        await handle_agent_event(event)

    # Aggregate events over time windows
    aggregator = EventAggregator(
        config=AggregationConfig(
            window_type=WindowType.TUMBLING,
            window_size_seconds=60,
        ),
    )
    stats = await aggregator.aggregate(stream, security_context=context)
    ```
"""

from yoda_foundation.events.streaming.event_aggregator import (
    AggregationConfig,
    AggregationResult,
    AggregationType,
    DetectedPattern,
    EventAggregator,
    PatternConfig,
    PatternDetector,
    WindowType,
)
from yoda_foundation.events.streaming.event_stream import (
    BackpressureStrategy,
    EventStream,
    StreamConfig,
    StreamStats,
)


__all__ = [
    # Event Stream
    "EventStream",
    "StreamConfig",
    "BackpressureStrategy",
    "StreamStats",
    # Event Aggregator
    "EventAggregator",
    "AggregationConfig",
    "WindowType",
    "AggregationType",
    "AggregationResult",
    "PatternDetector",
    "PatternConfig",
    "DetectedPattern",
]
