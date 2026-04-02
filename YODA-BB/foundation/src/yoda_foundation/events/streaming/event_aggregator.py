"""
Event aggregator for aggregating events over time windows.

This module provides event aggregation capabilities with various
window types, aggregation functions, and pattern detection.

Example:
    ```python
    from yoda_foundation.events.streaming import (
        EventAggregator,
        AggregationConfig,
        WindowType,
        AggregationType,
        PatternDetector,
        PatternConfig,
    )

    # Create aggregator
    aggregator = EventAggregator(
        config=AggregationConfig(
            window_type=WindowType.TUMBLING,
            window_size_seconds=60,
            aggregations=[
                AggregationType.COUNT,
                AggregationType.SUM,
            ],
        ),
    )

    # Aggregate events
    result = await aggregator.aggregate_events(events, security_context)
    print(f"Count: {result.count}")
    print(f"Events by type: {result.by_type}")

    # Pattern detection
    detector = PatternDetector(
        config=PatternConfig(
            threshold=10,
            window_seconds=60,
        ),
    )
    patterns = await detector.detect(events, security_context)
    for pattern in patterns:
        print(f"Detected: {pattern.pattern_type} - {pattern.description}")
    ```
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from statistics import mean, median, stdev
from typing import Any

from yoda_foundation.events.bus.event_bus import Event
from yoda_foundation.exceptions import ValidationError
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


class WindowType(Enum):
    """
    Type of time window for aggregation.

    Defines how events are grouped into windows.

    Attributes:
        TUMBLING: Fixed-size, non-overlapping windows
        SLIDING: Fixed-size windows that slide by a step
        SESSION: Windows based on activity gaps
        GLOBAL: Single window containing all events

    Example:
        ```python
        # Tumbling: |------|------|------|
        # Sliding:  |------|
        #             |------|
        #                |------|
        # Session:  |------|    |----------|
        #           (gap separates sessions)
        ```
    """

    TUMBLING = "tumbling"
    SLIDING = "sliding"
    SESSION = "session"
    GLOBAL = "global"


class AggregationType(Enum):
    """
    Type of aggregation to perform.

    Defines the statistical function to apply.

    Attributes:
        COUNT: Count of events
        SUM: Sum of numeric field
        AVG: Average of numeric field
        MIN: Minimum value
        MAX: Maximum value
        MEDIAN: Median value
        STDEV: Standard deviation
        DISTINCT: Count of distinct values
        RATE: Events per second
        PERCENTILE: Percentile values

    Example:
        ```python
        aggregations = [
            AggregationType.COUNT,
            AggregationType.AVG,
            AggregationType.RATE,
        ]
        ```
    """

    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"
    STDEV = "stdev"
    DISTINCT = "distinct"
    RATE = "rate"
    PERCENTILE = "percentile"


@dataclass
class AggregationConfig:
    """
    Configuration for event aggregation.

    Attributes:
        window_type: Type of time window
        window_size_seconds: Window size in seconds
        slide_size_seconds: Slide size for sliding windows
        session_gap_seconds: Gap threshold for session windows
        aggregations: List of aggregations to compute
        group_by_field: Field to group events by
        value_field: Field to aggregate (for numeric aggregations)
        percentiles: Percentile values to compute

    Example:
        ```python
        config = AggregationConfig(
            window_type=WindowType.TUMBLING,
            window_size_seconds=60,
            aggregations=[
                AggregationType.COUNT,
                AggregationType.AVG,
            ],
            group_by_field="event_type",
            value_field="payload.latency_ms",
        )
        ```
    """

    window_type: WindowType = WindowType.TUMBLING
    window_size_seconds: int = 60
    slide_size_seconds: int = 10
    session_gap_seconds: int = 30
    aggregations: list[AggregationType] = field(default_factory=lambda: [AggregationType.COUNT])
    group_by_field: str | None = None
    value_field: str | None = None
    percentiles: list[int] = field(default_factory=lambda: [50, 90, 95, 99])

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.window_size_seconds < 1:
            raise ValidationError(
                message="window_size_seconds must be >= 1",
                field_name="window_size_seconds",
            )
        if self.slide_size_seconds < 1:
            raise ValidationError(
                message="slide_size_seconds must be >= 1",
                field_name="slide_size_seconds",
            )
        if self.session_gap_seconds < 1:
            raise ValidationError(
                message="session_gap_seconds must be >= 1",
                field_name="session_gap_seconds",
            )


@dataclass
class AggregationResult:
    """
    Result of event aggregation.

    Contains computed aggregation values and metadata.

    Attributes:
        window_start: Start of the aggregation window
        window_end: End of the aggregation window
        count: Number of events
        sum_value: Sum of values
        avg_value: Average value
        min_value: Minimum value
        max_value: Maximum value
        median_value: Median value
        stdev_value: Standard deviation
        distinct_count: Count of distinct values
        rate_per_second: Events per second
        percentile_values: Percentile values
        by_type: Count by event type
        by_group: Aggregations by group

    Example:
        ```python
        result = await aggregator.aggregate_events(events, security_context)
        print(f"Total: {result.count}")
        print(f"Average latency: {result.avg_value:.2f}ms")
        print(f"By type: {result.by_type}")
        ```
    """

    window_start: datetime
    window_end: datetime
    count: int = 0
    sum_value: float | None = None
    avg_value: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    median_value: float | None = None
    stdev_value: float | None = None
    distinct_count: int | None = None
    rate_per_second: float | None = None
    percentile_values: dict[int, float] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    by_group: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        """Get window duration in seconds."""
        return (self.window_end - self.window_start).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "duration_seconds": self.duration_seconds,
            "count": self.count,
            "sum_value": self.sum_value,
            "avg_value": self.avg_value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "median_value": self.median_value,
            "stdev_value": self.stdev_value,
            "distinct_count": self.distinct_count,
            "rate_per_second": self.rate_per_second,
            "percentile_values": self.percentile_values,
            "by_type": self.by_type,
            "by_group": self.by_group,
        }


class EventAggregator:
    """
    Event aggregator for computing statistics over time windows.

    Supports various window types and aggregation functions.

    Attributes:
        config: Aggregation configuration

    Example:
        ```python
        # Create aggregator
        aggregator = EventAggregator(
            config=AggregationConfig(
                window_type=WindowType.TUMBLING,
                window_size_seconds=60,
                aggregations=[
                    AggregationType.COUNT,
                    AggregationType.AVG,
                    AggregationType.RATE,
                ],
                value_field="payload.latency_ms",
            ),
        )

        # Aggregate events
        result = await aggregator.aggregate_events(events, security_context)
        print(f"Count: {result.count}")
        print(f"Average: {result.avg_value}")
        print(f"Rate: {result.rate_per_second}/sec")

        # Aggregate by group
        aggregator = EventAggregator(
            config=AggregationConfig(
                window_type=WindowType.GLOBAL,
                aggregations=[AggregationType.COUNT],
                group_by_field="event_type",
            ),
        )
        result = await aggregator.aggregate_events(events, security_context)
        for group, stats in result.by_group.items():
            print(f"{group}: {stats['count']}")
        ```

    Raises:
        ValidationError: If configuration is invalid
    """

    def __init__(self, config: AggregationConfig | None = None) -> None:
        """
        Initialize event aggregator.

        Args:
            config: Aggregation configuration
        """
        self.config = config or AggregationConfig()
        self._logger = logging.getLogger(__name__)

    async def aggregate_events(
        self,
        events: list[Event],
        security_context: SecurityContext,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> AggregationResult:
        """
        Aggregate a list of events.

        Args:
            events: Events to aggregate
            security_context: Security context for authorization
            window_start: Override window start time
            window_end: Override window end time

        Returns:
            Aggregation result

        Example:
            ```python
            result = await aggregator.aggregate_events(
                events,
                security_context,
            )
            print(f"Total: {result.count}")
            ```
        """
        security_context.require_permission("event.aggregate")

        if not events:
            now = datetime.now(UTC)
            return AggregationResult(
                window_start=window_start or now,
                window_end=window_end or now,
            )

        # Determine window bounds
        timestamps = [e.timestamp for e in events]
        start = window_start or min(timestamps)
        end = window_end or max(timestamps)

        # Initialize result
        result = AggregationResult(
            window_start=start,
            window_end=end,
            count=len(events),
        )

        # Count by type
        result.by_type = self._count_by_type(events)

        # Extract values if value_field specified
        values: list[float] = []
        if self.config.value_field:
            values = self._extract_values(events, self.config.value_field)

        # Compute requested aggregations
        for agg_type in self.config.aggregations:
            self._compute_aggregation(result, events, values, agg_type)

        # Group by field if specified
        if self.config.group_by_field:
            result.by_group = self._aggregate_by_group(events, values)

        return result

    async def aggregate_windows(
        self,
        events: list[Event],
        security_context: SecurityContext,
    ) -> list[AggregationResult]:
        """
        Aggregate events into multiple time windows.

        Args:
            events: Events to aggregate
            security_context: Security context for authorization

        Returns:
            List of aggregation results, one per window

        Example:
            ```python
            windows = await aggregator.aggregate_windows(
                events,
                security_context,
            )
            for window in windows:
                print(f"{window.window_start}: {window.count} events")
            ```
        """
        security_context.require_permission("event.aggregate")

        if not events:
            return []

        # Get window boundaries
        windows = self._get_windows(events)

        # Aggregate each window
        results = []
        for start, end in windows:
            window_events = [e for e in events if start <= e.timestamp <= end]
            result = await self.aggregate_events(
                window_events,
                security_context,
                window_start=start,
                window_end=end,
            )
            results.append(result)

        return results

    def _count_by_type(self, events: list[Event]) -> dict[str, int]:
        """Count events by type."""
        counts: dict[str, int] = defaultdict(int)
        for event in events:
            counts[event.event_type] += 1
        return dict(counts)

    def _extract_values(
        self,
        events: list[Event],
        field: str,
    ) -> list[float]:
        """Extract numeric values from events."""
        values = []
        for event in events:
            value = self._get_field_value(event, field)
            if value is not None:
                try:
                    values.append(float(value))
                except (TypeError, ValueError):
                    pass
        return values

    def _get_field_value(self, event: Event, field: str) -> Any:
        """Get field value from event using dot notation."""
        data = event.to_dict()
        for part in field.split("."):
            if isinstance(data, dict) and part in data:
                data = data[part]
            else:
                return None
        return data

    def _compute_aggregation(
        self,
        result: AggregationResult,
        events: list[Event],
        values: list[float],
        agg_type: AggregationType,
    ) -> None:
        """Compute a single aggregation type."""
        if agg_type == AggregationType.COUNT:
            result.count = len(events)
        elif agg_type == AggregationType.SUM and values:
            result.sum_value = sum(values)
        elif agg_type == AggregationType.AVG and values:
            result.avg_value = mean(values)
        elif agg_type == AggregationType.MIN and values:
            result.min_value = min(values)
        elif agg_type == AggregationType.MAX and values:
            result.max_value = max(values)
        elif agg_type == AggregationType.MEDIAN and values:
            result.median_value = median(values)
        elif agg_type == AggregationType.STDEV and len(values) > 1:
            result.stdev_value = stdev(values)
        elif agg_type == AggregationType.DISTINCT:
            # Distinct event IDs
            result.distinct_count = len(set(e.event_id for e in events))
        elif agg_type == AggregationType.RATE:
            duration = result.duration_seconds
            if duration > 0:
                result.rate_per_second = len(events) / duration
        elif agg_type == AggregationType.PERCENTILE and values:
            sorted_values = sorted(values)
            n = len(sorted_values)
            for p in self.config.percentiles:
                idx = int((p / 100) * n)
                idx = min(idx, n - 1)
                result.percentile_values[p] = sorted_values[idx]

    def _aggregate_by_group(
        self,
        events: list[Event],
        values: list[float],
    ) -> dict[str, dict[str, Any]]:
        """Aggregate events by group field."""
        if not self.config.group_by_field:
            return {}

        # Group events
        groups: dict[str, list[tuple[Event, float | None]]] = defaultdict(list)
        for i, event in enumerate(events):
            group_key = self._get_field_value(event, self.config.group_by_field)
            if group_key is not None:
                value = values[i] if i < len(values) else None
                groups[str(group_key)].append((event, value))

        # Compute aggregations per group
        result: dict[str, dict[str, Any]] = {}
        for group_key, group_items in groups.items():
            group_events = [item[0] for item in group_items]
            group_values = [item[1] for item in group_items if item[1] is not None]

            group_stats: dict[str, Any] = {"count": len(group_events)}

            if group_values:
                if AggregationType.SUM in self.config.aggregations:
                    group_stats["sum"] = sum(group_values)
                if AggregationType.AVG in self.config.aggregations:
                    group_stats["avg"] = mean(group_values)
                if AggregationType.MIN in self.config.aggregations:
                    group_stats["min"] = min(group_values)
                if AggregationType.MAX in self.config.aggregations:
                    group_stats["max"] = max(group_values)

            result[group_key] = group_stats

        return result

    def _get_windows(
        self,
        events: list[Event],
    ) -> list[tuple[datetime, datetime]]:
        """Get window boundaries based on configuration."""
        if not events:
            return []

        timestamps = sorted(e.timestamp for e in events)
        min_time = timestamps[0]
        max_time = timestamps[-1]

        if self.config.window_type == WindowType.GLOBAL:
            return [(min_time, max_time)]

        elif self.config.window_type == WindowType.TUMBLING:
            windows = []
            window_delta = timedelta(seconds=self.config.window_size_seconds)
            current_start = min_time
            while current_start <= max_time:
                current_end = current_start + window_delta
                windows.append((current_start, current_end))
                current_start = current_end
            return windows

        elif self.config.window_type == WindowType.SLIDING:
            windows = []
            window_delta = timedelta(seconds=self.config.window_size_seconds)
            slide_delta = timedelta(seconds=self.config.slide_size_seconds)
            current_start = min_time
            while current_start <= max_time:
                current_end = current_start + window_delta
                windows.append((current_start, current_end))
                current_start += slide_delta
            return windows

        elif self.config.window_type == WindowType.SESSION:
            windows = []
            session_gap = timedelta(seconds=self.config.session_gap_seconds)
            session_start = timestamps[0]
            session_end = timestamps[0]

            for ts in timestamps[1:]:
                if ts - session_end > session_gap:
                    # End current session
                    windows.append((session_start, session_end))
                    session_start = ts
                session_end = ts

            # Add last session
            windows.append((session_start, session_end))
            return windows

        return [(min_time, max_time)]


# =============================================================================
# Pattern Detection
# =============================================================================


class PatternType(Enum):
    """
    Types of patterns that can be detected.

    Attributes:
        SPIKE: Sudden increase in event rate
        DROP: Sudden decrease in event rate
        ANOMALY: Unusual event pattern
        SEQUENCE: Specific event sequence detected
        THRESHOLD: Threshold exceeded
        TREND: Increasing or decreasing trend

    Example:
        ```python
        if pattern.pattern_type == PatternType.SPIKE:
            await send_alert("Event spike detected")
        ```
    """

    SPIKE = "spike"
    DROP = "drop"
    ANOMALY = "anomaly"
    SEQUENCE = "sequence"
    THRESHOLD = "threshold"
    TREND = "trend"


@dataclass
class DetectedPattern:
    """
    A detected pattern in event stream.

    Attributes:
        pattern_type: Type of pattern detected
        description: Human-readable description
        confidence: Confidence score (0-1)
        start_time: When pattern started
        end_time: When pattern ended
        affected_events: Event IDs involved
        metadata: Additional pattern data

    Example:
        ```python
        for pattern in patterns:
            print(f"{pattern.pattern_type.value}: {pattern.description}")
            print(f"Confidence: {pattern.confidence:.2%}")
        ```
    """

    pattern_type: PatternType
    description: str
    confidence: float
    start_time: datetime
    end_time: datetime
    affected_events: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pattern_type": self.pattern_type.value,
            "description": self.description,
            "confidence": self.confidence,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "affected_events": self.affected_events,
            "metadata": self.metadata,
        }


@dataclass
class PatternConfig:
    """
    Configuration for pattern detection.

    Attributes:
        threshold: Event count threshold for spike detection
        window_seconds: Time window for pattern detection
        min_confidence: Minimum confidence to report pattern
        detect_spikes: Enable spike detection
        detect_drops: Enable drop detection
        detect_sequences: Enable sequence detection
        sequences: List of event type sequences to detect

    Example:
        ```python
        config = PatternConfig(
            threshold=10,
            window_seconds=60,
            min_confidence=0.8,
            detect_spikes=True,
            sequences=[
                ["user.login", "user.action", "user.logout"],
            ],
        )
        ```
    """

    threshold: int = 10
    window_seconds: int = 60
    min_confidence: float = 0.5
    detect_spikes: bool = True
    detect_drops: bool = True
    detect_sequences: bool = False
    sequences: list[list[str]] = field(default_factory=list)


class PatternDetector:
    """
    Pattern detector for event streams.

    Detects patterns like spikes, drops, and sequences in events.

    Attributes:
        config: Pattern detection configuration

    Example:
        ```python
        detector = PatternDetector(
            config=PatternConfig(
                threshold=100,
                window_seconds=60,
                min_confidence=0.8,
                detect_spikes=True,
            ),
        )

        patterns = await detector.detect(events, security_context)
        for pattern in patterns:
            if pattern.pattern_type == PatternType.SPIKE:
                await send_spike_alert(pattern)
        ```
    """

    def __init__(self, config: PatternConfig | None = None) -> None:
        """
        Initialize pattern detector.

        Args:
            config: Pattern detection configuration
        """
        self.config = config or PatternConfig()
        self._logger = logging.getLogger(__name__)

    async def detect(
        self,
        events: list[Event],
        security_context: SecurityContext,
    ) -> list[DetectedPattern]:
        """
        Detect patterns in events.

        Args:
            events: Events to analyze
            security_context: Security context for authorization

        Returns:
            List of detected patterns

        Example:
            ```python
            patterns = await detector.detect(events, security_context)
            for pattern in patterns:
                print(f"Detected: {pattern.pattern_type.value}")
            ```
        """
        security_context.require_permission("event.pattern.detect")

        patterns: list[DetectedPattern] = []

        if not events:
            return patterns

        # Detect spikes
        if self.config.detect_spikes:
            spike_patterns = self._detect_spikes(events)
            patterns.extend(spike_patterns)

        # Detect drops
        if self.config.detect_drops:
            drop_patterns = self._detect_drops(events)
            patterns.extend(drop_patterns)

        # Detect sequences
        if self.config.detect_sequences and self.config.sequences:
            sequence_patterns = self._detect_sequences(events)
            patterns.extend(sequence_patterns)

        # Filter by confidence
        patterns = [p for p in patterns if p.confidence >= self.config.min_confidence]

        return patterns

    def _detect_spikes(self, events: list[Event]) -> list[DetectedPattern]:
        """Detect event rate spikes."""
        patterns = []

        if len(events) < 2:
            return patterns

        # Sort by timestamp
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        # Calculate events per window
        window_delta = timedelta(seconds=self.config.window_seconds)
        window_counts: list[tuple[datetime, datetime, int, list[str]]] = []

        start = sorted_events[0].timestamp
        end = sorted_events[-1].timestamp

        current = start
        while current < end:
            window_end = current + window_delta
            window_events = [e for e in sorted_events if current <= e.timestamp < window_end]
            if window_events:
                window_counts.append(
                    (
                        current,
                        window_end,
                        len(window_events),
                        [e.event_id for e in window_events],
                    )
                )
            current = window_end

        # Find spikes (windows significantly above threshold)
        if len(window_counts) < 2:
            return patterns

        counts = [wc[2] for wc in window_counts]
        avg_count = mean(counts) if counts else 0

        for window_start, window_end, count, event_ids in window_counts:
            if count >= self.config.threshold and count > avg_count * 2:
                confidence = min(1.0, (count - avg_count) / avg_count)
                patterns.append(
                    DetectedPattern(
                        pattern_type=PatternType.SPIKE,
                        description=(
                            f"Event spike detected: {count} events in "
                            f"{self.config.window_seconds}s (threshold: {self.config.threshold})"
                        ),
                        confidence=confidence,
                        start_time=window_start,
                        end_time=window_end,
                        affected_events=event_ids,
                        metadata={
                            "count": count,
                            "threshold": self.config.threshold,
                            "avg_count": avg_count,
                        },
                    )
                )

        return patterns

    def _detect_drops(self, events: list[Event]) -> list[DetectedPattern]:
        """Detect event rate drops."""
        patterns = []

        if len(events) < 2:
            return patterns

        # Sort by timestamp
        sorted_events = sorted(events, key=lambda e: e.timestamp)

        # Calculate events per window
        window_delta = timedelta(seconds=self.config.window_seconds)
        window_counts: list[tuple[datetime, datetime, int]] = []

        start = sorted_events[0].timestamp
        end = sorted_events[-1].timestamp

        current = start
        while current < end:
            window_end = current + window_delta
            count = len([e for e in sorted_events if current <= e.timestamp < window_end])
            window_counts.append((current, window_end, count))
            current = window_end

        # Find drops (windows significantly below average)
        if len(window_counts) < 2:
            return patterns

        counts = [wc[2] for wc in window_counts]
        avg_count = mean(counts) if counts else 0

        for i, (window_start, window_end, count) in enumerate(window_counts):
            # Check if this is a significant drop from previous window
            if i > 0 and avg_count > 0:
                prev_count = window_counts[i - 1][2]
                if prev_count > 0 and count < prev_count * 0.5:
                    confidence = min(1.0, (prev_count - count) / prev_count)
                    patterns.append(
                        DetectedPattern(
                            pattern_type=PatternType.DROP,
                            description=(
                                f"Event drop detected: {count} events (previous: {prev_count})"
                            ),
                            confidence=confidence,
                            start_time=window_start,
                            end_time=window_end,
                            metadata={
                                "count": count,
                                "prev_count": prev_count,
                                "avg_count": avg_count,
                            },
                        )
                    )

        return patterns

    def _detect_sequences(self, events: list[Event]) -> list[DetectedPattern]:
        """Detect specific event sequences."""
        patterns = []

        # Sort by timestamp
        sorted_events = sorted(events, key=lambda e: e.timestamp)
        event_types = [e.event_type for e in sorted_events]

        for sequence in self.config.sequences:
            if len(sequence) > len(event_types):
                continue

            # Find all occurrences of the sequence
            for i in range(len(event_types) - len(sequence) + 1):
                if event_types[i : i + len(sequence)] == sequence:
                    start_event = sorted_events[i]
                    end_event = sorted_events[i + len(sequence) - 1]
                    affected = [sorted_events[j].event_id for j in range(i, i + len(sequence))]

                    patterns.append(
                        DetectedPattern(
                            pattern_type=PatternType.SEQUENCE,
                            description=f"Sequence detected: {' -> '.join(sequence)}",
                            confidence=1.0,
                            start_time=start_event.timestamp,
                            end_time=end_event.timestamp,
                            affected_events=affected,
                            metadata={"sequence": sequence},
                        )
                    )

        return patterns


__all__ = [
    "AggregationConfig",
    "AggregationResult",
    "AggregationType",
    "DetectedPattern",
    "EventAggregator",
    "PatternConfig",
    "PatternDetector",
    "PatternType",
    "WindowType",
]
