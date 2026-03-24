"""
Event metrics for tracking event rates, latencies, and errors.

This module provides metrics collection and monitoring for events
including counters, histograms, and rate tracking.

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

    # Record events
    await metrics.record_event(event, security_context)

    # Record latency
    await metrics.record_latency(
        "handler.process",
        latency_ms=150.5,
        security_context=security_context,
    )

    # Record error
    await metrics.record_error(
        "handler.process",
        error_type="timeout",
        security_context=security_context,
    )

    # Get summary
    summary = await metrics.get_summary(security_context)
    print(f"Total events: {summary['total_events']}")
    print(f"Error rate: {summary['error_rate']:.2%}")
    print(f"P99 latency: {summary['latency_p99']:.2f}ms")

    # Export for Prometheus
    prometheus_format = metrics.export_prometheus()
    ```
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from statistics import mean
from typing import Any

from yoda_foundation.events.bus.event_bus import Event
from yoda_foundation.exceptions import ValidationError
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


class MetricType(Enum):
    """
    Types of metrics that can be tracked.

    Attributes:
        COUNTER: Monotonically increasing counter
        GAUGE: Point-in-time value
        HISTOGRAM: Distribution of values
        RATE: Events per time unit

    Example:
        ```python
        metrics.register(
            name="events_total",
            metric_type=MetricType.COUNTER,
        )
        ```
    """

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    RATE = "rate"


@dataclass
class HistogramBucket:
    """
    Bucket for histogram metric.

    Attributes:
        le: Less than or equal threshold
        count: Number of observations in bucket

    Example:
        ```python
        bucket = HistogramBucket(le=100.0, count=50)
        # 50 observations <= 100ms
        ```
    """

    le: float  # less than or equal
    count: int = 0


@dataclass
class MetricsConfig:
    """
    Configuration for event metrics.

    Attributes:
        histogram_buckets: Bucket boundaries for histograms
        window_size_seconds: Time window for rate calculations
        max_samples: Maximum samples to retain for histograms
        labels_max_cardinality: Maximum unique label combinations
        export_interval_seconds: Interval for metric export
        enable_percentiles: Calculate percentiles for histograms

    Example:
        ```python
        config = MetricsConfig(
            histogram_buckets=[10, 50, 100, 250, 500, 1000, 5000],
            window_size_seconds=60,
            enable_percentiles=True,
        )
        ```
    """

    histogram_buckets: list[float] = field(
        default_factory=lambda: [10, 50, 100, 250, 500, 1000, 5000]
    )
    window_size_seconds: int = 60
    max_samples: int = 10000
    labels_max_cardinality: int = 1000
    export_interval_seconds: int = 15
    enable_percentiles: bool = True
    percentiles: list[int] = field(default_factory=lambda: [50, 90, 95, 99])

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.window_size_seconds < 1:
            raise ValidationError(
                message="window_size_seconds must be >= 1",
                field_name="window_size_seconds",
            )
        if self.max_samples < 100:
            raise ValidationError(
                message="max_samples must be >= 100",
                field_name="max_samples",
            )


@dataclass
class MetricsSummary:
    """
    Summary of collected metrics.

    Attributes:
        total_events: Total events processed
        events_by_type: Count by event type
        error_count: Total errors
        error_rate: Error rate (0-1)
        latency_avg_ms: Average latency
        latency_p50_ms: P50 latency
        latency_p90_ms: P90 latency
        latency_p95_ms: P95 latency
        latency_p99_ms: P99 latency
        rate_per_second: Events per second
        window_start: Start of measurement window
        window_end: End of measurement window

    Example:
        ```python
        summary = await metrics.get_summary(security_context)
        print(f"Total: {summary.total_events}")
        print(f"Errors: {summary.error_count} ({summary.error_rate:.2%})")
        print(f"P99 latency: {summary.latency_p99_ms:.2f}ms")
        ```
    """

    total_events: int = 0
    events_by_type: dict[str, int] = field(default_factory=dict)
    error_count: int = 0
    error_rate: float = 0.0
    latency_avg_ms: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p90_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    rate_per_second: float = 0.0
    window_start: datetime | None = None
    window_end: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_events": self.total_events,
            "events_by_type": self.events_by_type,
            "error_count": self.error_count,
            "error_rate": self.error_rate,
            "latency_avg_ms": self.latency_avg_ms,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p90_ms": self.latency_p90_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_p99_ms": self.latency_p99_ms,
            "rate_per_second": self.rate_per_second,
            "window_start": (self.window_start.isoformat() if self.window_start else None),
            "window_end": self.window_end.isoformat() if self.window_end else None,
        }


class EventMetrics:
    """
    Event metrics collector for monitoring event system health.

    Tracks event counts, latencies, error rates, and throughput
    with support for labels and time windows.

    Attributes:
        config: Metrics configuration

    Example:
        ```python
        # Create metrics
        metrics = EventMetrics(
            config=MetricsConfig(
                histogram_buckets=[10, 50, 100, 500, 1000],
                window_size_seconds=60,
            ),
        )

        # Start metrics collection
        await metrics.start()

        # Record events
        await metrics.record_event(event, security_context)

        # Record latency with labels
        await metrics.record_latency(
            name="handler.process",
            latency_ms=150.5,
            security_context=security_context,
            labels={"handler": "notification_handler"},
        )

        # Record error
        await metrics.record_error(
            name="handler.process",
            error_type="timeout",
            security_context=security_context,
        )

        # Get summary
        summary = await metrics.get_summary(security_context)
        print(f"Total events: {summary.total_events}")
        print(f"Error rate: {summary.error_rate:.2%}")

        # Export for monitoring systems
        prometheus = metrics.export_prometheus()
        json_metrics = metrics.export_json()

        # Stop metrics
        await metrics.stop()
        ```

    Raises:
        ValidationError: If configuration is invalid
    """

    def __init__(self, config: MetricsConfig | None = None) -> None:
        """
        Initialize event metrics.

        Args:
            config: Metrics configuration
        """
        self.config = config or MetricsConfig()

        # Event counters
        self._event_counts: dict[str, int] = defaultdict(int)
        self._event_timestamps: deque[tuple[float, str]] = deque()

        # Error tracking
        self._error_counts: dict[str, int] = defaultdict(int)
        self._error_timestamps: deque[tuple[float, str]] = deque()

        # Latency tracking
        self._latency_samples: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.config.max_samples)
        )
        self._latency_histograms: dict[str, list[HistogramBucket]] = {}

        # Rate tracking
        self._rate_windows: dict[str, deque[float]] = defaultdict(deque)

        # Custom metrics
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}

        # State
        self._running = False
        self._start_time: datetime | None = None
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """
        Start metrics collection.

        Example:
            ```python
            await metrics.start()
            ```
        """
        self._running = True
        self._start_time = datetime.now(UTC)

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        self._logger.info("Event metrics started")

    async def stop(self) -> None:
        """
        Stop metrics collection.

        Example:
            ```python
            await metrics.stop()
            ```
        """
        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        self._logger.info("Event metrics stopped")

    async def record_event(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Record an event occurrence.

        Args:
            event: Event to record
            security_context: Security context for authorization

        Example:
            ```python
            await metrics.record_event(event, security_context)
            ```
        """
        security_context.require_permission("metrics.record")

        async with self._lock:
            now = time.time()

            # Increment counter
            self._event_counts[event.event_type] += 1
            self._event_counts["_total"] += 1

            # Record timestamp for rate calculation
            self._event_timestamps.append((now, event.event_type))

            # Clean old timestamps
            cutoff = now - self.config.window_size_seconds
            while self._event_timestamps and self._event_timestamps[0][0] < cutoff:
                self._event_timestamps.popleft()

    async def record_latency(
        self,
        name: str,
        latency_ms: float,
        security_context: SecurityContext,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        Record a latency measurement.

        Args:
            name: Metric name
            latency_ms: Latency in milliseconds
            security_context: Security context for authorization
            labels: Optional labels for the metric

        Example:
            ```python
            await metrics.record_latency(
                "handler.process",
                150.5,
                security_context,
                labels={"handler": "notification"},
            )
            ```
        """
        security_context.require_permission("metrics.record")

        async with self._lock:
            # Build metric key with labels
            key = self._build_key(name, labels)

            # Record sample
            self._latency_samples[key].append(latency_ms)

            # Update histogram
            self._update_histogram(key, latency_ms)

    async def record_error(
        self,
        name: str,
        error_type: str,
        security_context: SecurityContext,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        Record an error occurrence.

        Args:
            name: Metric name
            error_type: Type of error
            security_context: Security context for authorization
            labels: Optional labels for the metric

        Example:
            ```python
            await metrics.record_error(
                "handler.process",
                "timeout",
                security_context,
            )
            ```
        """
        security_context.require_permission("metrics.record")

        async with self._lock:
            now = time.time()
            key = f"{name}:{error_type}"

            # Increment counter
            self._error_counts[key] += 1
            self._error_counts["_total"] += 1

            # Record timestamp
            self._error_timestamps.append((now, key))

            # Clean old timestamps
            cutoff = now - self.config.window_size_seconds
            while self._error_timestamps and self._error_timestamps[0][0] < cutoff:
                self._error_timestamps.popleft()

    async def increment_counter(
        self,
        name: str,
        value: int,
        security_context: SecurityContext,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        Increment a custom counter.

        Args:
            name: Counter name
            value: Value to add
            security_context: Security context for authorization
            labels: Optional labels

        Example:
            ```python
            await metrics.increment_counter(
                "webhooks_sent",
                1,
                security_context,
            )
            ```
        """
        security_context.require_permission("metrics.record")

        async with self._lock:
            key = self._build_key(name, labels)
            self._counters[key] += value

    async def set_gauge(
        self,
        name: str,
        value: float,
        security_context: SecurityContext,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        Set a gauge value.

        Args:
            name: Gauge name
            value: Value to set
            security_context: Security context for authorization
            labels: Optional labels

        Example:
            ```python
            await metrics.set_gauge(
                "queue_size",
                42.0,
                security_context,
            )
            ```
        """
        security_context.require_permission("metrics.record")

        async with self._lock:
            key = self._build_key(name, labels)
            self._gauges[key] = value

    async def get_summary(
        self,
        security_context: SecurityContext,
    ) -> MetricsSummary:
        """
        Get metrics summary.

        Args:
            security_context: Security context for authorization

        Returns:
            Metrics summary

        Example:
            ```python
            summary = await metrics.get_summary(security_context)
            print(f"Total events: {summary.total_events}")
            ```
        """
        security_context.require_permission("metrics.read")

        async with self._lock:
            now = datetime.now(UTC)
            window_start = now - timedelta(seconds=self.config.window_size_seconds)

            summary = MetricsSummary(
                total_events=self._event_counts.get("_total", 0),
                events_by_type={k: v for k, v in self._event_counts.items() if k != "_total"},
                error_count=self._error_counts.get("_total", 0),
                window_start=window_start,
                window_end=now,
            )

            # Calculate error rate
            if summary.total_events > 0:
                summary.error_rate = summary.error_count / summary.total_events

            # Calculate rate
            window_events = sum(
                1
                for ts, _ in self._event_timestamps
                if ts >= time.time() - self.config.window_size_seconds
            )
            summary.rate_per_second = window_events / self.config.window_size_seconds

            # Calculate latency percentiles
            all_samples = []
            for samples in self._latency_samples.values():
                all_samples.extend(samples)

            if all_samples:
                sorted_samples = sorted(all_samples)
                n = len(sorted_samples)

                summary.latency_avg_ms = mean(sorted_samples)
                summary.latency_p50_ms = sorted_samples[int(n * 0.50)]
                summary.latency_p90_ms = sorted_samples[int(n * 0.90)]
                summary.latency_p95_ms = sorted_samples[int(n * 0.95)]
                summary.latency_p99_ms = sorted_samples[min(int(n * 0.99), n - 1)]

            return summary

    async def get_histogram(
        self,
        name: str,
        security_context: SecurityContext,
        labels: dict[str, str] | None = None,
    ) -> list[HistogramBucket]:
        """
        Get histogram buckets for a metric.

        Args:
            name: Metric name
            security_context: Security context for authorization
            labels: Optional labels

        Returns:
            List of histogram buckets

        Example:
            ```python
            buckets = await metrics.get_histogram(
                "handler.latency",
                security_context,
            )
            for bucket in buckets:
                print(f"<= {bucket.le}ms: {bucket.count}")
            ```
        """
        security_context.require_permission("metrics.read")

        async with self._lock:
            key = self._build_key(name, labels)
            return self._latency_histograms.get(key, [])

    async def get_rate(
        self,
        name: str,
        security_context: SecurityContext,
        window_seconds: int | None = None,
    ) -> float:
        """
        Get rate per second for a metric.

        Args:
            name: Metric name
            security_context: Security context for authorization
            window_seconds: Time window (default: config window)

        Returns:
            Rate per second

        Example:
            ```python
            rate = await metrics.get_rate("events", security_context)
            print(f"Rate: {rate:.2f}/sec")
            ```
        """
        security_context.require_permission("metrics.read")

        window = window_seconds or self.config.window_size_seconds

        async with self._lock:
            if name == "events":
                count = sum(1 for ts, _ in self._event_timestamps if ts >= time.time() - window)
            elif name == "errors":
                count = sum(1 for ts, _ in self._error_timestamps if ts >= time.time() - window)
            else:
                count = 0

            return count / window if window > 0 else 0

    def export_prometheus(self) -> str:
        """
        Export metrics in Prometheus format.

        Returns:
            Prometheus-formatted metrics string

        Example:
            ```python
            prometheus_metrics = metrics.export_prometheus()
            ```
        """
        lines = []

        # Event counters
        lines.append("# HELP events_total Total number of events")
        lines.append("# TYPE events_total counter")
        for event_type, count in self._event_counts.items():
            if event_type != "_total":
                safe_type = event_type.replace(".", "_")
                lines.append(f'events_total{{type="{safe_type}"}} {count}')

        # Error counters
        lines.append("# HELP errors_total Total number of errors")
        lines.append("# TYPE errors_total counter")
        for error_key, count in self._error_counts.items():
            if error_key != "_total":
                lines.append(f'errors_total{{error="{error_key}"}} {count}')

        # Latency histograms
        lines.append("# HELP latency_seconds Latency histogram")
        lines.append("# TYPE latency_seconds histogram")
        for key, buckets in self._latency_histograms.items():
            for bucket in buckets:
                lines.append(
                    f'latency_seconds_bucket{{name="{key}",le="{bucket.le / 1000}"}} {bucket.count}'
                )

        # Custom counters
        lines.append("# HELP custom_counter Custom counter metrics")
        lines.append("# TYPE custom_counter counter")
        for key, value in self._counters.items():
            lines.append(f'custom_counter{{name="{key}"}} {value}')

        # Gauges
        lines.append("# HELP custom_gauge Custom gauge metrics")
        lines.append("# TYPE custom_gauge gauge")
        for key, value in self._gauges.items():
            lines.append(f'custom_gauge{{name="{key}"}} {value}')

        return "\n".join(lines)

    def export_json(self) -> dict[str, Any]:
        """
        Export metrics as JSON.

        Returns:
            Dictionary of metrics

        Example:
            ```python
            metrics_json = metrics.export_json()
            ```
        """
        return {
            "events": dict(self._event_counts),
            "errors": dict(self._error_counts),
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "latency_histograms": {
                key: [{"le": b.le, "count": b.count} for b in buckets]
                for key, buckets in self._latency_histograms.items()
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def reset(self, security_context: SecurityContext) -> None:
        """
        Reset all metrics.

        Args:
            security_context: Security context for authorization

        Example:
            ```python
            await metrics.reset(security_context)
            ```
        """
        security_context.require_permission("metrics.reset")

        async with self._lock:
            self._event_counts.clear()
            self._event_timestamps.clear()
            self._error_counts.clear()
            self._error_timestamps.clear()
            self._latency_samples.clear()
            self._latency_histograms.clear()
            self._counters.clear()
            self._gauges.clear()
            self._rate_windows.clear()

        self._logger.info("Metrics reset")

    def _build_key(
        self,
        name: str,
        labels: dict[str, str] | None = None,
    ) -> str:
        """Build metric key with labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def _update_histogram(self, key: str, value: float) -> None:
        """Update histogram with new value."""
        # Initialize histogram if needed
        if key not in self._latency_histograms:
            self._latency_histograms[key] = [
                HistogramBucket(le=b) for b in self.config.histogram_buckets
            ]
            # Add +Inf bucket
            self._latency_histograms[key].append(HistogramBucket(le=float("inf")))

        # Update bucket counts
        for bucket in self._latency_histograms[key]:
            if value <= bucket.le:
                bucket.count += 1

    async def _cleanup_loop(self) -> None:
        """Background task to clean up old metrics."""
        while self._running:
            try:
                await asyncio.sleep(self.config.export_interval_seconds)
                await self._cleanup_old_data()
            except asyncio.CancelledError:
                break
            except (OSError, ValueError) as e:
                self._logger.error(f"Metrics cleanup error: {e}")

    async def _cleanup_old_data(self) -> None:
        """Clean up old timestamps outside window."""
        async with self._lock:
            cutoff = time.time() - self.config.window_size_seconds

            # Clean event timestamps
            while self._event_timestamps and self._event_timestamps[0][0] < cutoff:
                self._event_timestamps.popleft()

            # Clean error timestamps
            while self._error_timestamps and self._error_timestamps[0][0] < cutoff:
                self._error_timestamps.popleft()


__all__ = [
    "EventMetrics",
    "HistogramBucket",
    "MetricType",
    "MetricsConfig",
    "MetricsSummary",
]
