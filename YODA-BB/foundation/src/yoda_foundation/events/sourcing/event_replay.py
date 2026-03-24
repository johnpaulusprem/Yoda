"""
Event replay for event sourcing in the Agentic AI Component Library.

This module provides functionality to replay events from the event store
for rebuilding projections, creating read models, or migrating data.

Example:
    ```python
    from yoda_foundation.events.sourcing import EventReplay, EventStore

    # Create replay manager
    store = EventStore(connection_string)
    await store.connect()

    replay = EventReplay(event_store=store)

    # Replay entire stream
    await replay.replay_stream(
        stream_name="order-123",
        handler=rebuild_order_projection,
        security_context=context,
    )

    # Replay from specific version
    await replay.replay_from(
        position=1000,
        handler=update_read_model,
        security_context=context,
    )

    # Selective replay with filter
    await replay.replay_selective(
        event_types=["order.created", "order.completed"],
        handler=process_order_events,
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from yoda_foundation.events.sourcing.event_store import EventRecord, EventStore
from yoda_foundation.exceptions import ValidationError
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)


# Type alias for replay handlers
ReplayHandler = Callable[[EventRecord], Awaitable[None]]


class ReplayError(Exception):
    """Exception raised during event replay."""

    pass


@dataclass
class ReplayProgress:
    """
    Progress tracking for event replay.

    Attributes:
        total_events: Total number of events to replay
        processed_events: Number of events processed
        failed_events: Number of events that failed
        start_time: When replay started
        end_time: When replay completed
        current_position: Current position in replay
        errors: List of error messages

    Example:
        ```python
        progress = replay.get_progress()
        print(f"Progress: {progress.processed_events}/{progress.total_events}")
        print(f"Success rate: {progress.success_rate():.2%}")
        ```
    """

    total_events: int = 0
    processed_events: int = 0
    failed_events: int = 0
    start_time: datetime | None = None
    end_time: datetime | None = None
    current_position: int = 0
    errors: list[str] = field(default_factory=list)

    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.processed_events == 0:
            return 0.0
        return (self.processed_events - self.failed_events) / self.processed_events

    def is_complete(self) -> bool:
        """Check if replay is complete."""
        return self.end_time is not None

    def to_dict(self) -> dict[str, Any]:
        """Convert progress to dictionary."""
        return {
            "total_events": self.total_events,
            "processed_events": self.processed_events,
            "failed_events": self.failed_events,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "current_position": self.current_position,
            "success_rate": self.success_rate(),
            "is_complete": self.is_complete(),
            "error_count": len(self.errors),
        }


class EventReplay:
    """
    Event replay manager for rebuilding projections and read models.

    Provides functionality to:
    - Replay entire streams
    - Replay from specific positions
    - Selective replay by event type
    - Progress tracking
    - Error handling and recovery

    Attributes:
        event_store: Event store to replay from
        batch_size: Number of events to process per batch
        continue_on_error: Whether to continue on handler errors

    Example:
        ```python
        # Create replay manager
        replay = EventReplay(
            event_store=store,
            batch_size=100,
            continue_on_error=True,
        )

        # Replay stream
        progress = await replay.replay_stream(
            stream_name="user-123",
            handler=rebuild_user_projection,
            security_context=context,
        )

        print(f"Replayed {progress.processed_events} events")

        # Replay all events from position
        await replay.replay_from(
            position=1000,
            handler=update_analytics,
            security_context=context,
        )

        # Selective replay
        await replay.replay_selective(
            event_types=["user.created", "user.updated"],
            from_position=0,
            handler=rebuild_user_index,
            security_context=context,
        )
        ```

    Raises:
        ReplayError: If replay fails
        ValidationError: If parameters are invalid
    """

    def __init__(
        self,
        event_store: EventStore,
        batch_size: int = 100,
        continue_on_error: bool = True,
    ) -> None:
        """
        Initialize event replay manager.

        Args:
            event_store: Event store to replay from
            batch_size: Events per batch
            continue_on_error: Continue on handler errors
        """
        if batch_size < 1:
            raise ValidationError(
                message=f"batch_size must be >= 1, got {batch_size}",
                field_name="batch_size",
            )

        self.event_store = event_store
        self.batch_size = batch_size
        self.continue_on_error = continue_on_error
        self._progress: dict[str, ReplayProgress] = {}
        self._logger = logging.getLogger(__name__)

    async def replay_stream(
        self,
        stream_name: str,
        handler: ReplayHandler,
        from_version: int = 1,
        to_version: int | None = None,
        *,
        security_context: SecurityContext,
    ) -> ReplayProgress:
        """
        Replay events from a specific stream.

        Args:
            stream_name: Name of stream to replay
            handler: Async handler for each event
            from_version: Starting version (inclusive)
            to_version: Ending version (inclusive), None for all
            security_context: Security context for authorization

        Returns:
            Replay progress information

        Raises:
            ReplayError: If replay fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            async def rebuild_projection(record: EventRecord) -> None:
                # Update projection based on event
                await update_projection(record.event)

            progress = await replay.replay_stream(
                stream_name="order-123",
                handler=rebuild_projection,
                from_version=1,
                security_context=context,
            )

            print(f"Replayed {progress.processed_events} events")
            ```
        """
        # Check permission
        security_context.require_permission("event.replay")

        replay_id = f"stream:{stream_name}"
        progress = ReplayProgress(start_time=datetime.now(UTC))
        self._progress[replay_id] = progress

        try:
            # Read events from stream
            records = await self.event_store.read_stream(
                stream_name=stream_name,
                from_version=from_version,
                to_version=to_version,
                security_context=security_context,
            )

            progress.total_events = len(records)

            self._logger.info(
                f"Starting replay of stream '{stream_name}'",
                extra={
                    "stream_name": stream_name,
                    "total_events": progress.total_events,
                    "from_version": from_version,
                    "to_version": to_version,
                },
            )

            # Process events
            for record in records:
                await self._process_event(record, handler, progress)

            # Mark complete
            progress.end_time = datetime.now(UTC)

            self._logger.info(
                f"Completed replay of stream '{stream_name}'",
                extra={
                    "stream_name": stream_name,
                    "processed": progress.processed_events,
                    "failed": progress.failed_events,
                    "success_rate": progress.success_rate(),
                },
            )

            return progress

        except (OSError, ValueError, TypeError) as e:
            progress.end_time = datetime.now(UTC)
            progress.errors.append(str(e))
            raise ReplayError(f"Failed to replay stream '{stream_name}': {e}") from e

    async def replay_from(
        self,
        position: int,
        handler: ReplayHandler,
        security_context: SecurityContext,
        max_events: int | None = None,
    ) -> ReplayProgress:
        """
        Replay all events from a specific position.

        Useful for rebuilding projections from a checkpoint.

        Args:
            position: Starting position (inclusive)
            handler: Async handler for each event
            security_context: Security context for authorization
            max_events: Maximum number of events to replay

        Returns:
            Replay progress information

        Raises:
            ReplayError: If replay fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            # Resume from checkpoint
            checkpoint_position = 1000

            async def update_read_model(record: EventRecord) -> None:
                await read_model.apply(record.event)

            progress = await replay.replay_from(
                position=checkpoint_position,
                handler=update_read_model,
                security_context=context,
            )
            ```
        """
        # Check permission
        security_context.require_permission("event.replay")

        replay_id = f"position:{position}"
        progress = ReplayProgress(
            start_time=datetime.now(UTC),
            current_position=position,
        )
        self._progress[replay_id] = progress

        try:
            self._logger.info(
                f"Starting replay from position {position}",
                extra={"position": position, "max_events": max_events},
            )

            events_processed = 0

            # Stream events from position
            async for record in self.event_store.read_all(
                from_position=position,
                batch_size=self.batch_size,
                security_context=security_context,
            ):
                if max_events and events_processed >= max_events:
                    break

                await self._process_event(record, handler, progress)
                progress.current_position = record.position
                events_processed += 1

            progress.total_events = events_processed
            progress.end_time = datetime.now(UTC)

            self._logger.info(
                f"Completed replay from position {position}",
                extra={
                    "position": position,
                    "processed": progress.processed_events,
                    "failed": progress.failed_events,
                },
            )

            return progress

        except (OSError, ValueError, TypeError) as e:
            progress.end_time = datetime.now(UTC)
            progress.errors.append(str(e))
            raise ReplayError(f"Failed to replay from position {position}: {e}") from e

    async def replay_selective(
        self,
        event_types: list[str],
        handler: ReplayHandler,
        from_position: int = 1,
        to_position: int | None = None,
        *,
        security_context: SecurityContext,
    ) -> ReplayProgress:
        """
        Replay only specific event types.

        Useful for rebuilding projections that only care about certain events.

        Args:
            event_types: List of event types to replay
            handler: Async handler for each event
            from_position: Starting position (inclusive)
            to_position: Ending position (inclusive), None for all
            security_context: Security context for authorization

        Returns:
            Replay progress information

        Raises:
            ReplayError: If replay fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            # Rebuild order analytics from order events only
            await replay.replay_selective(
                event_types=["order.created", "order.completed", "order.cancelled"],
                handler=update_order_analytics,
                security_context=context,
            )
            ```
        """
        # Check permission
        security_context.require_permission("event.replay")

        if not event_types:
            raise ValidationError(
                message="event_types cannot be empty",
                field_name="event_types",
            )

        replay_id = f"selective:{','.join(event_types)}"
        progress = ReplayProgress(
            start_time=datetime.now(UTC),
            current_position=from_position,
        )
        self._progress[replay_id] = progress

        try:
            event_type_set = set(event_types)

            self._logger.info(
                f"Starting selective replay of event types: {event_types}",
                extra={
                    "event_types": event_types,
                    "from_position": from_position,
                    "to_position": to_position,
                },
            )

            events_processed = 0

            # Stream and filter events
            async for record in self.event_store.read_all(
                from_position=from_position,
                batch_size=self.batch_size,
                security_context=security_context,
            ):
                if to_position and record.position > to_position:
                    break

                # Filter by event type
                if record.event.event_type in event_type_set:
                    await self._process_event(record, handler, progress)

                progress.current_position = record.position
                events_processed += 1

            progress.total_events = events_processed
            progress.end_time = datetime.now(UTC)

            self._logger.info(
                "Completed selective replay",
                extra={
                    "event_types": event_types,
                    "processed": progress.processed_events,
                    "failed": progress.failed_events,
                },
            )

            return progress

        except (OSError, ValueError, TypeError) as e:
            progress.end_time = datetime.now(UTC)
            progress.errors.append(str(e))
            raise ReplayError(f"Failed selective replay: {e}") from e

    async def replay_parallel(
        self,
        stream_names: list[str],
        handler: ReplayHandler,
        security_context: SecurityContext,
        max_concurrent: int = 5,
    ) -> dict[str, ReplayProgress]:
        """
        Replay multiple streams in parallel.

        Args:
            stream_names: List of streams to replay
            handler: Async handler for each event
            security_context: Security context for authorization
            max_concurrent: Maximum concurrent replays

        Returns:
            Dictionary mapping stream names to progress

        Raises:
            ReplayError: If any replay fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            # Rebuild projections for multiple users in parallel
            user_streams = ["user-1", "user-2", "user-3"]

            results = await replay.replay_parallel(
                stream_names=user_streams,
                handler=rebuild_user_projection,
                security_context=context,
                max_concurrent=3,
            )

            for stream, progress in results.items():
                print(f"{stream}: {progress.processed_events} events")
            ```
        """
        # Check permission
        security_context.require_permission("event.replay")

        if not stream_names:
            raise ValidationError(
                message="stream_names cannot be empty",
                field_name="stream_names",
            )

        self._logger.info(
            f"Starting parallel replay of {len(stream_names)} streams",
            extra={"stream_count": len(stream_names), "max_concurrent": max_concurrent},
        )

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(max_concurrent)

        async def replay_with_semaphore(stream_name: str) -> tuple[str, ReplayProgress]:
            async with semaphore:
                progress = await self.replay_stream(
                    stream_name=stream_name,
                    handler=handler,
                    security_context=security_context,
                )
                return stream_name, progress

        # Execute replays in parallel
        tasks = [replay_with_semaphore(stream) for stream in stream_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        progress_map = {}
        errors = []

        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                stream_name, progress = result
                progress_map[stream_name] = progress

        if errors:
            raise ReplayError(f"Parallel replay had errors: {errors}")

        self._logger.info(
            f"Completed parallel replay of {len(stream_names)} streams",
            extra={"stream_count": len(stream_names), "successful": len(progress_map)},
        )

        return progress_map

    async def _process_event(
        self,
        record: EventRecord,
        handler: ReplayHandler,
        progress: ReplayProgress,
    ) -> None:
        """
        Process a single event with error handling.

        Args:
            record: Event record to process
            handler: Handler function
            progress: Progress tracker
        """
        try:
            await handler(record)
            progress.processed_events += 1

        except (ValueError, TypeError, KeyError, OSError) as e:
            progress.failed_events += 1
            error_msg = f"Handler failed for event {record.event.event_id}: {e}"
            progress.errors.append(error_msg)

            self._logger.error(
                error_msg,
                exc_info=e,
                extra={
                    "event_id": record.event.event_id,
                    "event_type": record.event.event_type,
                    "position": record.position,
                },
            )

            if not self.continue_on_error:
                raise ReplayError(error_msg) from e

    def get_progress(self, replay_id: str) -> ReplayProgress | None:
        """
        Get progress for a specific replay.

        Args:
            replay_id: Replay identifier

        Returns:
            Progress information or None if not found

        Example:
            ```python
            progress = replay.get_progress("stream:order-123")
            if progress:
                print(f"Progress: {progress.processed_events}/{progress.total_events}")
            ```
        """
        return self._progress.get(replay_id)

    def clear_progress(self, replay_id: str) -> None:
        """
        Clear progress for a replay.

        Args:
            replay_id: Replay identifier

        Example:
            ```python
            replay.clear_progress("stream:order-123")
            ```
        """
        if replay_id in self._progress:
            del self._progress[replay_id]
