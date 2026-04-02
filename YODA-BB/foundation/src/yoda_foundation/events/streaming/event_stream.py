"""
Event stream for real-time event processing.

This module provides an event stream implementation with backpressure
handling, filtering, mapping, and statistics tracking.

Example:
    ```python
    from yoda_foundation.events.streaming import (
        EventStream,
        StreamConfig,
        BackpressureStrategy,
    )
    from yoda_foundation.events import Event

    # Create stream
    stream = EventStream(
        config=StreamConfig(
            buffer_size=1000,
            backpressure_strategy=BackpressureStrategy.DROP_OLDEST,
        ),
    )

    # Start stream
    await stream.start()

    # Push events
    await stream.push(event, security_context)

    # Iterate events
    async for event in stream.iterate(security_context=context):
        await process(event)

    # Filter events
    async for event in stream.filter(
        lambda e: e.event_type.startswith("agent."),
        security_context=context,
    ):
        await handle_agent_event(event)

    # Map events
    async for mapped in stream.map(
        lambda e: e.payload,
        security_context=context,
    ):
        await process_payload(mapped)

    # Stop stream
    await stream.stop()
    ```
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import (
    Any,
    TypeVar,
)

from yoda_foundation.events.bus.event_bus import Event
from yoda_foundation.exceptions import (
    EventError,
    StreamBufferFullError,
    ValidationError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)

T = TypeVar("T")


class BackpressureStrategy(Enum):
    """
    Strategy for handling backpressure when buffer is full.

    Defines how the stream handles events when the buffer reaches capacity.

    Attributes:
        BLOCK: Block until space available (may cause upstream delays)
        DROP_OLDEST: Drop oldest events to make room
        DROP_NEWEST: Drop incoming events when full
        ERROR: Raise error when buffer is full

    Example:
        ```python
        config = StreamConfig(
            buffer_size=1000,
            backpressure_strategy=BackpressureStrategy.DROP_OLDEST,
        )
        ```
    """

    BLOCK = "block"
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    ERROR = "error"


@dataclass
class StreamConfig:
    """
    Configuration for event stream.

    Attributes:
        buffer_size: Maximum events in buffer
        backpressure_strategy: How to handle full buffer
        drain_timeout_seconds: Timeout when draining buffer
        batch_size: Events per batch for batch processing
        filter_duplicates: Whether to filter duplicate events
        duplicate_window_seconds: Time window for duplicate detection

    Example:
        ```python
        config = StreamConfig(
            buffer_size=1000,
            backpressure_strategy=BackpressureStrategy.DROP_OLDEST,
            drain_timeout_seconds=30.0,
            batch_size=100,
            filter_duplicates=True,
            duplicate_window_seconds=60,
        )
        ```
    """

    buffer_size: int = 1000
    backpressure_strategy: BackpressureStrategy = BackpressureStrategy.DROP_OLDEST
    drain_timeout_seconds: float = 30.0
    batch_size: int = 100
    filter_duplicates: bool = False
    duplicate_window_seconds: int = 60

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.buffer_size < 1:
            raise ValidationError(
                message=f"buffer_size must be >= 1, got {self.buffer_size}",
                field_name="buffer_size",
            )
        if self.drain_timeout_seconds <= 0:
            raise ValidationError(
                message="drain_timeout_seconds must be positive",
                field_name="drain_timeout_seconds",
            )
        if self.batch_size < 1:
            raise ValidationError(
                message=f"batch_size must be >= 1, got {self.batch_size}",
                field_name="batch_size",
            )


@dataclass
class StreamStats:
    """
    Statistics for event stream.

    Tracks performance and health metrics for the stream.

    Attributes:
        events_received: Total events received
        events_processed: Total events processed
        events_dropped: Total events dropped
        events_filtered: Events filtered out
        buffer_high_watermark: Maximum buffer usage
        current_buffer_size: Current buffer size
        processing_latency_ms: Average processing latency
        start_time: When stream started
        last_event_time: When last event was received

    Example:
        ```python
        stats = stream.get_stats()
        print(f"Received: {stats.events_received}")
        print(f"Dropped: {stats.events_dropped}")
        print(f"Drop rate: {stats.drop_rate:.2%}")
        ```
    """

    events_received: int = 0
    events_processed: int = 0
    events_dropped: int = 0
    events_filtered: int = 0
    buffer_high_watermark: int = 0
    current_buffer_size: int = 0
    processing_latency_ms: float = 0.0
    start_time: datetime | None = None
    last_event_time: datetime | None = None

    @property
    def drop_rate(self) -> float:
        """Calculate event drop rate."""
        if self.events_received == 0:
            return 0.0
        return self.events_dropped / self.events_received

    @property
    def throughput_per_second(self) -> float:
        """Calculate throughput per second."""
        if self.start_time is None:
            return 0.0
        elapsed = (datetime.now(UTC) - self.start_time).total_seconds()
        if elapsed == 0:
            return 0.0
        return self.events_processed / elapsed

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "events_received": self.events_received,
            "events_processed": self.events_processed,
            "events_dropped": self.events_dropped,
            "events_filtered": self.events_filtered,
            "buffer_high_watermark": self.buffer_high_watermark,
            "current_buffer_size": self.current_buffer_size,
            "processing_latency_ms": self.processing_latency_ms,
            "drop_rate": self.drop_rate,
            "throughput_per_second": self.throughput_per_second,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "last_event_time": (self.last_event_time.isoformat() if self.last_event_time else None),
        }


class EventStream:
    """
    Real-time event stream with backpressure handling.

    Provides async iteration, filtering, mapping, and batching
    capabilities for event processing.

    Attributes:
        config: Stream configuration

    Example:
        ```python
        # Create and start stream
        stream = EventStream(
            config=StreamConfig(
                buffer_size=1000,
                backpressure_strategy=BackpressureStrategy.DROP_OLDEST,
            ),
        )
        await stream.start()

        # Push events
        await stream.push(event, security_context)

        # Iterate events
        async for event in stream.iterate(security_context=context):
            await process(event)

        # Filter events
        async for event in stream.filter(
            lambda e: e.severity == EventSeverity.CRITICAL,
            security_context=context,
        ):
            await handle_critical(event)

        # Map events
        async for data in stream.map(
            lambda e: {"type": e.event_type, "payload": e.payload},
            security_context=context,
        ):
            await process_data(data)

        # Batch events
        async for batch in stream.batch(size=10, security_context=context):
            await process_batch(batch)

        # Stop stream
        await stream.stop()
        ```

    Raises:
        EventError: If stream operations fail
        StreamBufferFullError: If buffer is full and strategy is ERROR
    """

    def __init__(self, config: StreamConfig | None = None) -> None:
        """
        Initialize event stream.

        Args:
            config: Stream configuration
        """
        self.config = config or StreamConfig()
        self._buffer: deque[Event] = deque(maxlen=self.config.buffer_size)
        self._running = False
        self._stats = StreamStats()
        self._lock = asyncio.Lock()
        self._event_available = asyncio.Event()
        self._recent_event_ids: deque[tuple[str, float]] = deque()
        self._logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """
        Start the event stream.

        Example:
            ```python
            stream = EventStream()
            await stream.start()
            ```
        """
        self._running = True
        self._stats.start_time = datetime.now(UTC)
        self._logger.info(
            "Event stream started",
            extra={"buffer_size": self.config.buffer_size},
        )

    async def stop(self) -> None:
        """
        Stop the event stream.

        Waits for buffer to drain or timeout.

        Example:
            ```python
            await stream.stop()
            ```
        """
        self._running = False
        self._event_available.set()  # Wake up any waiting iterators

        # Wait for buffer to drain
        try:
            await asyncio.wait_for(
                self._drain_buffer(),
                timeout=self.config.drain_timeout_seconds,
            )
        except TimeoutError:
            self._logger.warning(f"Buffer drain timeout, {len(self._buffer)} events remaining")

        self._logger.info(
            "Event stream stopped",
            extra=self._stats.to_dict(),
        )

    async def push(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> bool:
        """
        Push an event to the stream.

        Args:
            event: Event to push
            security_context: Security context for authorization

        Returns:
            True if event was accepted, False if dropped

        Raises:
            StreamBufferFullError: If buffer is full and strategy is ERROR
            AuthorizationError: If user lacks permission

        Example:
            ```python
            accepted = await stream.push(event, security_context)
            if not accepted:
                logger.warning("Event was dropped")
            ```
        """
        security_context.require_permission("event.stream.push")

        if not self._running:
            raise EventError(
                message="Stream is not running",
                event_type="stream.not_running",
            )

        async with self._lock:
            self._stats.events_received += 1
            self._stats.last_event_time = datetime.now(UTC)

            # Check for duplicates
            if self.config.filter_duplicates and self._is_duplicate(event):
                self._stats.events_filtered += 1
                return False

            # Handle backpressure
            if len(self._buffer) >= self.config.buffer_size:
                if self.config.backpressure_strategy == BackpressureStrategy.ERROR:
                    raise StreamBufferFullError(
                        message="Event stream buffer is full",
                        buffer_size=self.config.buffer_size,
                    )
                elif self.config.backpressure_strategy == BackpressureStrategy.DROP_NEWEST:
                    self._stats.events_dropped += 1
                    return False
                elif self.config.backpressure_strategy == BackpressureStrategy.DROP_OLDEST:
                    self._buffer.popleft()
                    self._stats.events_dropped += 1
                elif self.config.backpressure_strategy == BackpressureStrategy.BLOCK:
                    # Wait for space (with timeout)
                    await self._wait_for_space()

            # Add to buffer
            self._buffer.append(event)
            self._stats.current_buffer_size = len(self._buffer)
            self._stats.buffer_high_watermark = max(
                self._stats.buffer_high_watermark, len(self._buffer)
            )

            # Track for duplicate detection
            if self.config.filter_duplicates:
                self._recent_event_ids.append((event.event_id, time.time()))
                self._cleanup_duplicate_tracker()

            # Signal that an event is available
            self._event_available.set()

            return True

    async def iterate(
        self,
        security_context: SecurityContext,
    ) -> AsyncIterator[Event]:
        """
        Iterate over events in the stream.

        Yields events as they become available.

        Args:
            security_context: Security context for authorization

        Yields:
            Events from the stream

        Example:
            ```python
            async for event in stream.iterate(security_context=context):
                await process(event)
            ```
        """
        security_context.require_permission("event.stream.iterate")

        while self._running or self._buffer:
            # Wait for events
            if not self._buffer:
                self._event_available.clear()
                try:
                    await asyncio.wait_for(
                        self._event_available.wait(),
                        timeout=1.0,
                    )
                except TimeoutError:
                    continue

            # Get event from buffer
            async with self._lock:
                if self._buffer:
                    event = self._buffer.popleft()
                    self._stats.current_buffer_size = len(self._buffer)
                    self._stats.events_processed += 1
                    yield event

    async def filter(
        self,
        predicate: Callable[[Event], bool],
        security_context: SecurityContext,
    ) -> AsyncIterator[Event]:
        """
        Filter events in the stream.

        Only yields events that match the predicate.

        Args:
            predicate: Function to filter events
            security_context: Security context for authorization

        Yields:
            Events matching the predicate

        Example:
            ```python
            # Filter by event type
            async for event in stream.filter(
                lambda e: e.event_type.startswith("agent."),
                security_context=context,
            ):
                await handle_agent_event(event)

            # Filter by severity
            async for event in stream.filter(
                lambda e: e.priority == EventPriority.HIGH,
                security_context=context,
            ):
                await handle_high_priority(event)
            ```
        """
        async for event in self.iterate(security_context):
            if predicate(event):
                yield event

    async def map(
        self,
        transform: Callable[[Event], T],
        security_context: SecurityContext,
    ) -> AsyncIterator[T]:
        """
        Map events to transformed values.

        Applies a transformation function to each event.

        Args:
            transform: Function to transform events
            security_context: Security context for authorization

        Yields:
            Transformed values

        Example:
            ```python
            # Extract payloads
            async for payload in stream.map(
                lambda e: e.payload,
                security_context=context,
            ):
                await process_payload(payload)

            # Transform to summary
            async for summary in stream.map(
                lambda e: {
                    "type": e.event_type,
                    "time": e.timestamp.isoformat(),
                },
                security_context=context,
            ):
                await log_summary(summary)
            ```
        """
        async for event in self.iterate(security_context):
            yield transform(event)

    async def batch(
        self,
        size: int,
        security_context: SecurityContext,
        timeout_seconds: float = 5.0,
    ) -> AsyncIterator[list[Event]]:
        """
        Batch events into groups.

        Yields batches of events when batch size is reached
        or timeout expires.

        Args:
            size: Batch size
            security_context: Security context for authorization
            timeout_seconds: Max time to wait for batch

        Yields:
            Batches of events

        Example:
            ```python
            async for batch in stream.batch(
                size=10,
                security_context=context,
                timeout_seconds=5.0,
            ):
                await process_batch(batch)
            ```
        """
        batch: list[Event] = []
        batch_start = time.time()

        async for event in self.iterate(security_context):
            batch.append(event)

            # Yield batch if size reached
            if len(batch) >= size:
                yield batch
                batch = []
                batch_start = time.time()
            # Yield batch if timeout expired
            elif time.time() - batch_start >= timeout_seconds:
                if batch:
                    yield batch
                    batch = []
                batch_start = time.time()

        # Yield remaining events
        if batch:
            yield batch

    async def take(
        self,
        n: int,
        security_context: SecurityContext,
    ) -> list[Event]:
        """
        Take n events from the stream.

        Args:
            n: Number of events to take
            security_context: Security context for authorization

        Returns:
            List of events

        Example:
            ```python
            events = await stream.take(10, security_context)
            ```
        """
        events: list[Event] = []
        async for event in self.iterate(security_context):
            events.append(event)
            if len(events) >= n:
                break
        return events

    async def peek(
        self,
        security_context: SecurityContext,
    ) -> Event | None:
        """
        Peek at the next event without removing it.

        Args:
            security_context: Security context for authorization

        Returns:
            Next event or None if buffer is empty

        Example:
            ```python
            event = await stream.peek(security_context)
            if event:
                print(f"Next event: {event.event_type}")
            ```
        """
        security_context.require_permission("event.stream.peek")

        async with self._lock:
            if self._buffer:
                return self._buffer[0]
        return None

    def get_stats(self) -> StreamStats:
        """
        Get stream statistics.

        Returns:
            Stream statistics

        Example:
            ```python
            stats = stream.get_stats()
            print(f"Throughput: {stats.throughput_per_second:.2f} events/sec")
            ```
        """
        return self._stats

    def reset_stats(self) -> None:
        """
        Reset stream statistics.

        Example:
            ```python
            stream.reset_stats()
            ```
        """
        self._stats = StreamStats(start_time=datetime.now(UTC) if self._running else None)

    async def clear(self, security_context: SecurityContext) -> int:
        """
        Clear the event buffer.

        Args:
            security_context: Security context for authorization

        Returns:
            Number of events cleared

        Example:
            ```python
            cleared = await stream.clear(security_context)
            print(f"Cleared {cleared} events")
            ```
        """
        security_context.require_permission("event.stream.clear")

        async with self._lock:
            count = len(self._buffer)
            self._buffer.clear()
            self._stats.current_buffer_size = 0
            return count

    def is_running(self) -> bool:
        """Check if stream is running."""
        return self._running

    def _is_duplicate(self, event: Event) -> bool:
        """Check if event is a duplicate."""
        for event_id, _ in self._recent_event_ids:
            if event_id == event.event_id:
                return True
        return False

    def _cleanup_duplicate_tracker(self) -> None:
        """Remove old entries from duplicate tracker."""
        cutoff = time.time() - self.config.duplicate_window_seconds
        while self._recent_event_ids and self._recent_event_ids[0][1] < cutoff:
            self._recent_event_ids.popleft()

    async def _wait_for_space(self) -> None:
        """Wait for space in buffer (for BLOCK strategy)."""
        while len(self._buffer) >= self.config.buffer_size:
            await asyncio.sleep(0.01)

    async def _drain_buffer(self) -> None:
        """Wait for buffer to be fully consumed."""
        while self._buffer:
            await asyncio.sleep(0.1)


__all__ = [
    "BackpressureStrategy",
    "EventStream",
    "StreamConfig",
    "StreamStats",
]
