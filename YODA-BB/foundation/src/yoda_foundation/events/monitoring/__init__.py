"""
Event monitoring module for the Agentic AI Component Library.

Provides event metrics tracking, monitoring, and analysis.

Example:
    ```python
    from yoda_foundation.events.monitoring import (
        EventMetrics,
        MetricsConfig,
        MetricType,
    )

    # Create metrics tracker
    metrics = EventMetrics(
        config=MetricsConfig(
            histogram_buckets=[10, 50, 100, 500, 1000],
            window_size_seconds=60,
        ),
    )

    # Record event
    await metrics.record_event(event, security_context)

    # Record latency
    await metrics.record_latency("handler.process", 150.5, security_context)

    # Get metrics
    summary = await metrics.get_summary(security_context)
    print(f"Total events: {summary['total_events']}")
    print(f"Error rate: {summary['error_rate']:.2%}")
    ```
"""

from yoda_foundation.events.monitoring.event_metrics import (
    EventMetrics,
    HistogramBucket,
    MetricsConfig,
    MetricsSummary,
    MetricType,
)


__all__ = [
    "EventMetrics",
    "HistogramBucket",
    "MetricType",
    "MetricsConfig",
    "MetricsSummary",
]
