"""
Event store for event sourcing in the Agentic AI Component Library.

This module provides an event store for persisting and retrieving events
in an event sourcing architecture with versioning and optimistic concurrency.

Example:
    ```python
    from yoda_foundation.events.sourcing import EventStore, EventRecord

    # Create event store
    store = EventStore(connection_string="postgresql://localhost/events")
    await store.connect()

    # Append events to stream
    events = [
        Event(event_type="agent.created", payload={"name": "Agent1"}),
        Event(event_type="agent.configured", payload={"config": {...}}),
    ]

    await store.append(
        stream_name="agent-123",
        events=events,
        expected_version=0,
        security_context=context,
    )

    # Read stream
    records = await store.read_stream(
        stream_name="agent-123",
        security_context=context,
    )

    # Read all events
    async for record in store.read_all(security_context=context):
        print(f"Event: {record.event.event_type}")

    await store.close()
    ```
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from yoda_foundation.events.bus.event_bus import Event
from yoda_foundation.exceptions import (
    ValidationError,
)
from yoda_foundation.security import SecurityContext


logger = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _validate_identifier(name: str, param_name: str) -> None:
    """Validate that a string is a safe SQL identifier.

    Args:
        name: The identifier to validate
        param_name: Parameter name for error messages

    Raises:
        ValueError: If the identifier contains invalid characters
    """
    if not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(
            f"Invalid SQL identifier for {param_name}: {name!r}. "
            "Only letters, digits, and underscores are allowed."
        )


@dataclass
class EventRecord:
    """
    Event record in the event store.

    Represents a persisted event with metadata.

    Attributes:
        event: The event data
        stream_name: Name of the event stream
        version: Version number in stream
        position: Global position in store
        recorded_at: When event was recorded
        metadata: Additional metadata

    Example:
        ```python
        record = EventRecord(
            event=event,
            stream_name="agent-123",
            version=5,
            position=1234,
            recorded_at=datetime.now(timezone.utc),
        )
        ```
    """

    event: Event
    stream_name: str
    version: int
    position: int
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary."""
        return {
            "event": self.event.to_dict(),
            "stream_name": self.stream_name,
            "version": self.version,
            "position": self.position,
            "recorded_at": self.recorded_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventRecord:
        """Create record from dictionary."""
        recorded_at = data.get("recorded_at")
        if isinstance(recorded_at, str):
            recorded_at = datetime.fromisoformat(recorded_at)
        elif recorded_at is None:
            recorded_at = datetime.now(UTC)

        return cls(
            event=Event.from_dict(data["event"]),
            stream_name=data["stream_name"],
            version=data["version"],
            position=data["position"],
            recorded_at=recorded_at,
            metadata=data.get("metadata", {}),
        )


class EventStoreError(Exception):
    """Base exception for event store errors."""

    pass


class ConcurrencyError(EventStoreError):
    """Raised when optimistic concurrency check fails."""

    def __init__(
        self,
        stream_name: str,
        expected_version: int,
        actual_version: int,
    ) -> None:
        """
        Initialize concurrency error.

        Args:
            stream_name: Name of stream
            expected_version: Expected version
            actual_version: Actual version
        """
        self.stream_name = stream_name
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"Concurrency conflict in stream '{stream_name}': "
            f"expected version {expected_version}, but actual is {actual_version}"
        )


class EventStore:
    """
    Event store for event sourcing.

    Provides append-only storage for events with:
    - Stream-based organization
    - Event versioning per stream
    - Global event ordering
    - Optimistic concurrency control
    - Efficient event replay

    Attributes:
        connection_string: Database connection string
        table_name: Name of events table
        streams_table: Name of streams metadata table

    Example:
        ```python
        # Create store
        store = EventStore(
            connection_string="postgresql://localhost/eventstore",
            table_name="events",
        )
        await store.connect()

        # Append to stream
        await store.append(
            stream_name="order-123",
            events=[order_created, item_added],
            expected_version=0,
            security_context=context,
        )

        # Read stream with version range
        records = await store.read_stream(
            stream_name="order-123",
            from_version=0,
            to_version=10,
            security_context=context,
        )

        # Read all events from position
        async for record in store.read_all(
            from_position=1000,
            security_context=context,
        ):
            await process_event(record)

        await store.close()
        ```

    Raises:
        EventStoreError: If store operations fail
        ConcurrencyError: If optimistic concurrency check fails
        ValidationError: If parameters are invalid
    """

    def __init__(
        self,
        connection_string: str,
        table_name: str = "events",
        streams_table: str = "streams",
    ) -> None:
        """
        Initialize event store.

        Args:
            connection_string: Database connection string
            table_name: Name of events table
            streams_table: Name of streams metadata table
        """
        self.connection_string = connection_string
        _validate_identifier(table_name, "table_name")
        _validate_identifier(streams_table, "streams_table")
        self.table_name = table_name
        self.streams_table = streams_table
        self._pool: Any | None = None
        self._logger = logging.getLogger(__name__)

    async def connect(self) -> None:
        """
        Connect to database and initialize schema.

        Creates tables if they don't exist.

        Raises:
            EventStoreError: If connection fails

        Example:
            ```python
            store = EventStore(connection_string)
            await store.connect()
            ```
        """
        try:
            import asyncpg

            # Create connection pool
            self._pool = await asyncpg.create_pool(
                self.connection_string,
                min_size=2,
                max_size=10,
                command_timeout=60,
            )

            # Initialize schema
            await self._initialize_schema()

            self._logger.info("Connected to event store database")

        except (ImportError, OSError, ConnectionError) as e:
            raise EventStoreError(f"Failed to connect to event store: {e}") from e

    async def close(self) -> None:
        """
        Close database connection.

        Example:
            ```python
            await store.close()
            ```
        """
        if self._pool:
            await self._pool.close()
            self._logger.info("Closed event store connection")

    async def append(
        self,
        stream_name: str,
        events: list[Event],
        expected_version: int,
        security_context: SecurityContext,
        metadata: dict[str, Any] | None = None,
    ) -> list[EventRecord]:
        """
        Append events to a stream.

        Uses optimistic concurrency control to ensure stream integrity.

        Args:
            stream_name: Name of the event stream
            events: Events to append
            expected_version: Expected current version (for concurrency check)
            security_context: Security context for authorization
            metadata: Additional metadata to attach

        Returns:
            List of created event records

        Raises:
            ConcurrencyError: If version check fails
            EventStoreError: If append fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            # Append to new stream (version 0)
            records = await store.append(
                stream_name="user-123",
                events=[user_created, email_set],
                expected_version=0,
                security_context=context,
            )

            # Append to existing stream
            current_version = 5
            records = await store.append(
                stream_name="user-123",
                events=[password_changed],
                expected_version=current_version,
                security_context=context,
            )
            ```
        """
        # Check permission
        security_context.require_permission("event.store.append")

        if not events:
            raise ValidationError(
                message="Cannot append empty event list",
                field_name="events",
            )

        if expected_version < 0:
            raise ValidationError(
                message=f"expected_version must be >= 0, got {expected_version}",
                field_name="expected_version",
            )

        try:
            async with self._pool.acquire() as conn, conn.transaction():
                # Check and update stream version
                current_version = await self._get_stream_version(
                    conn,
                    stream_name,
                )

                if current_version != expected_version:
                    raise ConcurrencyError(
                        stream_name=stream_name,
                        expected_version=expected_version,
                        actual_version=current_version,
                    )

                # Insert events
                records = []
                new_version = current_version

                for event in events:
                    new_version += 1

                    # Insert event
                    result = await conn.fetchrow(
                        f"""
                            INSERT INTO {self.table_name} (
                                stream_name,
                                version,
                                event_id,
                                event_type,
                                payload,
                                metadata,
                                event_metadata,
                                recorded_at
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            RETURNING position, recorded_at
                            """,
                        stream_name,
                        new_version,
                        event.event_id,
                        event.event_type,
                        event.payload,
                        metadata or {},
                        event.metadata,
                        datetime.now(UTC),
                    )

                    record = EventRecord(
                        event=event,
                        stream_name=stream_name,
                        version=new_version,
                        position=result["position"],
                        recorded_at=result["recorded_at"],
                        metadata=metadata or {},
                    )
                    records.append(record)

                # Update stream metadata
                await conn.execute(
                    f"""
                        INSERT INTO {self.streams_table} (
                            stream_name,
                            version,
                            updated_at
                        ) VALUES ($1, $2, $3)
                        ON CONFLICT (stream_name)
                        DO UPDATE SET
                            version = $2,
                            updated_at = $3
                        """,
                    stream_name,
                    new_version,
                    datetime.now(UTC),
                )

                self._logger.info(
                    f"Appended {len(events)} events to stream '{stream_name}'",
                    extra={
                        "stream_name": stream_name,
                        "count": len(events),
                        "new_version": new_version,
                    },
                )

                return records

        except ConcurrencyError:
            raise
        except (OSError, ValueError, TypeError) as e:
            raise EventStoreError(f"Failed to append events: {e}") from e

    async def read_stream(
        self,
        stream_name: str,
        from_version: int = 1,
        to_version: int | None = None,
        *,
        security_context: SecurityContext,
    ) -> list[EventRecord]:
        """
        Read events from a stream.

        Args:
            stream_name: Name of the stream
            from_version: Starting version (inclusive)
            to_version: Ending version (inclusive), None for all
            security_context: Security context for authorization

        Returns:
            List of event records

        Raises:
            EventStoreError: If read fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            # Read entire stream
            records = await store.read_stream(
                stream_name="order-123",
                security_context=context,
            )

            # Read version range
            records = await store.read_stream(
                stream_name="order-123",
                from_version=5,
                to_version=10,
                security_context=context,
            )
            ```
        """
        # Check permission
        security_context.require_permission("event.store.read")

        try:
            async with self._pool.acquire() as conn:
                if to_version is None:
                    query = f"""
                        SELECT * FROM {self.table_name}
                        WHERE stream_name = $1 AND version >= $2
                        ORDER BY version ASC
                    """
                    rows = await conn.fetch(query, stream_name, from_version)
                else:
                    query = f"""
                        SELECT * FROM {self.table_name}
                        WHERE stream_name = $1 AND version >= $2 AND version <= $3
                        ORDER BY version ASC
                    """
                    rows = await conn.fetch(query, stream_name, from_version, to_version)

                records = [self._row_to_record(row) for row in rows]

                self._logger.debug(
                    f"Read {len(records)} events from stream '{stream_name}'",
                    extra={
                        "stream_name": stream_name,
                        "count": len(records),
                        "from_version": from_version,
                        "to_version": to_version,
                    },
                )

                return records

        except (OSError, ValueError) as e:
            raise EventStoreError(f"Failed to read stream: {e}") from e

    async def read_all(
        self,
        from_position: int = 1,
        batch_size: int = 100,
        *,
        security_context: SecurityContext,
    ) -> AsyncIterator[EventRecord]:
        """
        Read all events from the store in order.

        Yields events in batches for efficient processing.

        Args:
            from_position: Starting position (inclusive)
            batch_size: Number of events per batch
            security_context: Security context for authorization

        Yields:
            Event records in order

        Raises:
            EventStoreError: If read fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            # Process all events
            async for record in store.read_all(security_context=context):
                await process_event(record)

            # Resume from position
            async for record in store.read_all(
                from_position=1000,
                security_context=context,
            ):
                await process_event(record)
            ```
        """
        # Check permission
        security_context.require_permission("event.store.read")

        try:
            current_position = from_position

            while True:
                async with self._pool.acquire() as conn:
                    query = f"""
                        SELECT * FROM {self.table_name}
                        WHERE position >= $1
                        ORDER BY position ASC
                        LIMIT $2
                    """
                    rows = await conn.fetch(query, current_position, batch_size)

                    if not rows:
                        break

                    for row in rows:
                        record = self._row_to_record(row)
                        yield record
                        current_position = record.position + 1

        except (OSError, ValueError) as e:
            raise EventStoreError(f"Failed to read all events: {e}") from e

    async def get_stream_version(
        self,
        stream_name: str,
        security_context: SecurityContext,
    ) -> int:
        """
        Get current version of a stream.

        Args:
            stream_name: Name of the stream
            security_context: Security context for authorization

        Returns:
            Current version (0 if stream doesn't exist)

        Raises:
            EventStoreError: If operation fails
            AuthorizationError: If user lacks permission

        Example:
            ```python
            version = await store.get_stream_version(
                "order-123",
                security_context,
            )
            print(f"Current version: {version}")
            ```
        """
        # Check permission
        security_context.require_permission("event.store.read")

        try:
            async with self._pool.acquire() as conn:
                return await self._get_stream_version(conn, stream_name)
        except (OSError, ValueError) as e:
            raise EventStoreError(f"Failed to get stream version: {e}") from e

    async def stream_exists(
        self,
        stream_name: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Check if stream exists.

        Args:
            stream_name: Name of the stream
            security_context: Security context for authorization

        Returns:
            True if stream exists

        Example:
            ```python
            if await store.stream_exists("order-123", security_context):
                print("Stream exists")
            ```
        """
        version = await self.get_stream_version(stream_name, security_context)
        return version > 0

    async def _get_stream_version(
        self,
        conn: Any,
        stream_name: str,
    ) -> int:
        """
        Get stream version using existing connection.

        Args:
            conn: Database connection
            stream_name: Name of stream

        Returns:
            Current version
        """
        row = await conn.fetchrow(
            f"SELECT version FROM {self.streams_table} WHERE stream_name = $1",
            stream_name,
        )
        return row["version"] if row else 0

    async def _initialize_schema(self) -> None:
        """Initialize database schema."""
        async with self._pool.acquire() as conn:
            # Create events table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    position BIGSERIAL PRIMARY KEY,
                    stream_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}',
                    event_metadata JSONB NOT NULL DEFAULT '{{}}',
                    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    UNIQUE (stream_name, version)
                )
            """)

            # Create indexes
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_stream
                ON {self.table_name} (stream_name, version)
            """)

            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_type
                ON {self.table_name} (event_type)
            """)

            # Create streams table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.streams_table} (
                    stream_name TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
                )
            """)

    def _row_to_record(self, row: Any) -> EventRecord:
        """
        Convert database row to event record.

        Args:
            row: Database row

        Returns:
            Event record
        """
        event = Event(
            event_id=row["event_id"],
            event_type=row["event_type"],
            payload=row["payload"],
            metadata=row["event_metadata"],
            timestamp=row["recorded_at"],
        )

        return EventRecord(
            event=event,
            stream_name=row["stream_name"],
            version=row["version"],
            position=row["position"],
            recorded_at=row["recorded_at"],
            metadata=row["metadata"],
        )
