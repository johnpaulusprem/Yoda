"""
Async event handler for non-blocking event processing.

This module provides an async event handler with queue-based processing,
batch handling, and configurable concurrency.

Example:
    ```python
    from yoda_foundation.events.handlers import (
        AsyncEventHandler,
        AsyncHandlerConfig,
    )

    # Create handler
    class MyAsyncHandler(AsyncEventHandler):
        name = "my_handler"

        async def process_event(
            self,
            event: Event,
            security_context: SecurityContext,
        ) -> None:
            await do_work(event)

    # Configure handler
    handler = MyAsyncHandler(
        config=AsyncHandlerConfig(
            queue_size=1000,
            max_workers=10,
            batch_size=50,
            batch_timeout_seconds=5.0,
        ),
    )

    # Start handler
    await handler.start()

    # Submit events
    await handler.submit(event, security_context)

    # Submit batch
    await handler.submit_batch(events, security_context)

    # Stop handler
    await handler.stop()
    ```
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from yoda_foundation.events.bus.event_bus import Event
from yoda_foundation.events.handlers.event_handler import EventHandler, HandlerConfig
from yoda_foundation.exceptions import (
    EventHandlerError,
    ValidationError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


@dataclass
class AsyncHandlerConfig(HandlerConfig):
    """
    Configuration for async event handler.

    Extends HandlerConfig with queue and batch settings.

    Attributes:
        queue_size: Maximum size of event queue
        max_workers: Maximum concurrent workers
        batch_size: Events per batch (0 for no batching)
        batch_timeout_seconds: Max time to wait for batch
        drain_timeout_seconds: Timeout when stopping handler
        process_interval_seconds: Interval between processing cycles

    Example:
        ```python
        config = AsyncHandlerConfig(
            queue_size=1000,
            max_workers=10,
            batch_size=50,
            batch_timeout_seconds=5.0,
            max_retries=3,
        )
        ```
    """

    queue_size: int = 1000
    max_workers: int = 10
    batch_size: int = 0  # 0 = no batching
    batch_timeout_seconds: float = 5.0
    drain_timeout_seconds: float = 30.0
    process_interval_seconds: float = 0.01

    def __post_init__(self) -> None:
        """Validate configuration."""
        super().__post_init__()
        if self.queue_size < 1:
            raise ValidationError(
                message=f"queue_size must be >= 1, got {self.queue_size}",
                field_name="queue_size",
            )
        if self.max_workers < 1:
            raise ValidationError(
                message=f"max_workers must be >= 1, got {self.max_workers}",
                field_name="max_workers",
            )


@dataclass
class HandlerStats:
    """
    Statistics for async handler.

    Tracks performance metrics for the handler.

    Attributes:
        events_queued: Total events queued
        events_processed: Total events processed
        events_failed: Total events failed
        events_dropped: Total events dropped (queue full)
        batches_processed: Total batches processed
        queue_high_watermark: Maximum queue size reached
        avg_processing_time_ms: Average processing time
        start_time: When handler started
        last_event_time: When last event was processed

    Example:
        ```python
        stats = handler.get_stats()
        print(f"Processed: {stats.events_processed}")
        print(f"Failed: {stats.events_failed}")
        ```
    """

    events_queued: int = 0
    events_processed: int = 0
    events_failed: int = 0
    events_dropped: int = 0
    batches_processed: int = 0
    queue_high_watermark: int = 0
    avg_processing_time_ms: float = 0.0
    start_time: datetime | None = None
    last_event_time: datetime | None = None
    _total_processing_time_ms: float = 0.0

    def record_processing_time(self, time_ms: float) -> None:
        """Record a processing time measurement."""
        self._total_processing_time_ms += time_ms
        if self.events_processed > 0:
            self.avg_processing_time_ms = self._total_processing_time_ms / self.events_processed

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "events_queued": self.events_queued,
            "events_processed": self.events_processed,
            "events_failed": self.events_failed,
            "events_dropped": self.events_dropped,
            "batches_processed": self.batches_processed,
            "queue_high_watermark": self.queue_high_watermark,
            "avg_processing_time_ms": self.avg_processing_time_ms,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "last_event_time": (self.last_event_time.isoformat() if self.last_event_time else None),
        }


class AsyncEventHandler(EventHandler):
    """
    Async event handler with queue-based processing.

    Provides non-blocking event handling with configurable
    concurrency and batch processing support.

    Subclasses must implement:
    - process_event: Handle a single event
    - can_handle: Check if handler can process an event

    Optionally override:
    - process_batch: Handle a batch of events

    Attributes:
        name: Handler name
        config: Handler configuration

    Example:
        ```python
        class NotificationHandler(AsyncEventHandler):
            name = "notification_handler"

            async def process_event(
                self,
                event: Event,
                security_context: SecurityContext,
            ) -> None:
                # Send notification
                await send_notification(event.payload)

            async def can_handle(self, event: Event) -> bool:
                return event.event_type.startswith("user.")

        # Create and start handler
        handler = NotificationHandler(
            config=AsyncHandlerConfig(
                queue_size=1000,
                max_workers=5,
            ),
        )
        await handler.start()

        # Submit events
        await handler.submit(event, security_context)

        # Get stats
        stats = handler.get_stats()
        print(f"Processed: {stats.events_processed}")

        # Stop handler
        await handler.stop()
        ```
    """

    name: str = "async_handler"

    def __init__(
        self,
        config: AsyncHandlerConfig | None = None,
    ) -> None:
        """
        Initialize async handler.

        Args:
            config: Handler configuration
        """
        self._async_config = config or AsyncHandlerConfig()
        super().__init__(config=self._async_config)

        self._queue: asyncio.Queue[tuple[Event, SecurityContext]] = asyncio.Queue(
            maxsize=self._async_config.queue_size
        )
        self._running = False
        self._workers: list[asyncio.Task[None]] = []
        self._stats = HandlerStats()
        self._semaphore = asyncio.Semaphore(self._async_config.max_workers)

    async def start(self) -> None:
        """
        Start the async handler.

        Spawns worker tasks to process events from the queue.

        Example:
            ```python
            await handler.start()
            ```
        """
        if self._running:
            return

        self._running = True
        self._stats.start_time = datetime.now(UTC)

        # Start worker tasks
        for i in range(self._async_config.max_workers):
            task = asyncio.create_task(self._worker(i))
            self._workers.append(task)

        self._logger.info(
            f"Started {self.name} with {self._async_config.max_workers} workers",
            extra={
                "handler": self.name,
                "workers": self._async_config.max_workers,
                "queue_size": self._async_config.queue_size,
            },
        )

    async def stop(self) -> None:
        """
        Stop the async handler.

        Waits for queue to drain or timeout.

        Example:
            ```python
            await handler.stop()
            ```
        """
        if not self._running:
            return

        self._running = False

        # Wait for queue to drain
        try:
            await asyncio.wait_for(
                self._queue.join(),
                timeout=self._async_config.drain_timeout_seconds,
            )
        except TimeoutError:
            self._logger.warning(
                f"Handler {self.name} drain timeout, {self._queue.qsize()} events remaining"
            )

        # Cancel workers
        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

        self._logger.info(
            f"Stopped {self.name}",
            extra=self._stats.to_dict(),
        )

    async def submit(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> bool:
        """
        Submit an event for async processing.

        Args:
            event: Event to process
            security_context: Security context

        Returns:
            True if event was queued, False if dropped

        Example:
            ```python
            queued = await handler.submit(event, security_context)
            if not queued:
                logger.warning("Event was dropped")
            ```
        """
        if not self._running:
            self._logger.warning(f"Handler {self.name} not running, dropping event")
            self._stats.events_dropped += 1
            return False

        try:
            self._queue.put_nowait((event, security_context))
            self._stats.events_queued += 1
            self._stats.queue_high_watermark = max(
                self._stats.queue_high_watermark, self._queue.qsize()
            )
            return True
        except asyncio.QueueFull:
            self._stats.events_dropped += 1
            self._logger.warning(
                f"Handler {self.name} queue full, dropping event",
                extra={"event_id": event.event_id},
            )
            return False

    async def submit_batch(
        self,
        events: list[Event],
        security_context: SecurityContext,
    ) -> int:
        """
        Submit a batch of events for processing.

        Args:
            events: Events to process
            security_context: Security context

        Returns:
            Number of events queued

        Example:
            ```python
            queued = await handler.submit_batch(events, security_context)
            print(f"Queued {queued}/{len(events)} events")
            ```
        """
        queued = 0
        for event in events:
            if await self.submit(event, security_context):
                queued += 1
        return queued

    @abstractmethod
    async def process_event(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Process a single event.

        Subclasses must implement this method.

        Args:
            event: Event to process
            security_context: Security context

        Raises:
            EventHandlerError: If processing fails

        Example:
            ```python
            async def process_event(
                self,
                event: Event,
                security_context: SecurityContext,
            ) -> None:
                await self.do_work(event.payload)
            ```
        """
        pass

    async def process_batch(
        self,
        events: list[Event],
        security_context: SecurityContext,
    ) -> None:
        """
        Process a batch of events.

        Override this method for batch-optimized processing.
        Default implementation calls process_event for each.

        Args:
            events: Events to process
            security_context: Security context

        Example:
            ```python
            async def process_batch(
                self,
                events: List[Event],
                security_context: SecurityContext,
            ) -> None:
                # Batch insert to database
                payloads = [e.payload for e in events]
                await db.insert_many(payloads)
            ```
        """
        for event in events:
            await self.process_event(event, security_context)

    async def handle(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """
        Handle an event (EventHandler interface).

        Submits event to the async queue.

        Args:
            event: Event to handle
            security_context: Security context
        """
        await self.submit(event, security_context)

    @abstractmethod
    async def can_handle(self, event: Event) -> bool:
        """
        Check if handler can process the event.

        Args:
            event: Event to check

        Returns:
            True if handler can process the event
        """
        pass

    def get_stats(self) -> HandlerStats:
        """
        Get handler statistics.

        Returns:
            Handler statistics

        Example:
            ```python
            stats = handler.get_stats()
            print(f"Queue: {handler.get_queue_size()}")
            print(f"Processed: {stats.events_processed}")
            ```
        """
        return self._stats

    def get_queue_size(self) -> int:
        """Get current queue size."""
        return self._queue.qsize()

    def is_running(self) -> bool:
        """Check if handler is running."""
        return self._running

    async def _worker(self, worker_id: int) -> None:
        """Worker task that processes events from queue."""
        self._logger.debug(f"Worker {worker_id} started for {self.name}")

        batch: list[tuple[Event, SecurityContext]] = []
        batch_start = time.time()

        while self._running or not self._queue.empty():
            try:
                # Get event from queue
                event, security_context = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self._async_config.process_interval_seconds,
                )

                # Add to batch if batching enabled
                if self._async_config.batch_size > 0:
                    batch.append((event, security_context))

                    # Process batch if size reached or timeout
                    should_process = (
                        len(batch) >= self._async_config.batch_size
                        or time.time() - batch_start >= self._async_config.batch_timeout_seconds
                    )

                    if should_process:
                        await self._process_batch_items(batch)
                        batch = []
                        batch_start = time.time()
                else:
                    # Process single event
                    await self._process_single(event, security_context)

                self._queue.task_done()

            except TimeoutError:
                # Process partial batch on timeout
                if batch and self._async_config.batch_size > 0:
                    if time.time() - batch_start >= self._async_config.batch_timeout_seconds:
                        await self._process_batch_items(batch)
                        batch = []
                        batch_start = time.time()
                continue
            except asyncio.CancelledError:
                break
            except (EventHandlerError, ValueError, TypeError) as e:
                self._logger.error(
                    f"Worker {worker_id} error: {e}",
                    exc_info=e,
                )

        # Process remaining batch
        if batch:
            await self._process_batch_items(batch)

        self._logger.debug(f"Worker {worker_id} stopped for {self.name}")

    async def _process_single(
        self,
        event: Event,
        security_context: SecurityContext,
    ) -> None:
        """Process a single event with error handling."""
        start_time = time.time()

        try:
            async with self._semaphore:
                await self.process_event(event, security_context)

            self._stats.events_processed += 1
            self._stats.last_event_time = datetime.now(UTC)

            processing_time = (time.time() - start_time) * 1000
            self._stats.record_processing_time(processing_time)

        except (EventHandlerError, ValueError, TypeError, KeyError) as e:
            self._stats.events_failed += 1
            self._logger.error(
                f"Event processing failed: {e}",
                exc_info=e,
                extra={"event_id": event.event_id},
            )

            # Call error hook
            await self.on_error(event, e)

    async def _process_batch_items(
        self,
        batch: list[tuple[Event, SecurityContext]],
    ) -> None:
        """Process a batch of items."""
        if not batch:
            return

        start_time = time.time()
        events = [item[0] for item in batch]
        security_context = batch[0][1]  # Use first context

        try:
            async with self._semaphore:
                await self.process_batch(events, security_context)

            self._stats.events_processed += len(events)
            self._stats.batches_processed += 1
            self._stats.last_event_time = datetime.now(UTC)

            processing_time = (time.time() - start_time) * 1000
            self._stats.record_processing_time(processing_time / len(events))

        except (EventHandlerError, ValueError, TypeError, KeyError) as e:
            self._stats.events_failed += len(events)
            self._logger.error(
                f"Batch processing failed: {e}",
                exc_info=e,
            )

            # Call error hook for each event
            for event, _ in batch:
                await self.on_error(event, e)


__all__ = [
    "AsyncEventHandler",
    "AsyncHandlerConfig",
    "HandlerStats",
]
