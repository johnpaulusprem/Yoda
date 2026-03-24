"""
Dead letter queue (DLQ) management for failed operations.

This module provides dead letter queue management with retry scheduling,
monitoring, and alerting capabilities.

Example:
    ```python
    from yoda_foundation.resilience.dead_letter import (
        DLQManager,
        DeadLetter,
    )
    from yoda_foundation.security import create_security_context

    # Create DLQ manager
    dlq = DLQManager(
        max_queue_size=10000,
        alert_threshold=100,
    )

    # Enqueue failed operation
    try:
        result = await risky_operation(data)
    except Exception as e:
        await dlq.enqueue(
            operation="risky_operation",
            payload=data,
            error=e,
            security_context=context,
        )

    # Check queue size
    stats = await dlq.get_statistics(security_context=context)
    print(f"Failed items: {stats['total_items']}")

    # Peek at next item
    item = await dlq.peek(
        operation="risky_operation",
        security_context=context,
    )

    # Dequeue for reprocessing
    item = await dlq.dequeue(
        operation="risky_operation",
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from yoda_foundation.exceptions import (
    ResilienceError,
    ValidationError,
)
from yoda_foundation.security.context import SecurityContext


logger = logging.getLogger(__name__)


class DeadLetterStatus(Enum):
    """Status of dead letter queue items."""

    PENDING = "pending"  # Waiting to be reprocessed
    REPROCESSING = "reprocessing"  # Currently being reprocessed
    COMPLETED = "completed"  # Successfully reprocessed
    FAILED = "failed"  # Reprocessing failed
    EXPIRED = "expired"  # TTL expired
    ABANDONED = "abandoned"  # Too many reprocess attempts


@dataclass
class DeadLetter:
    """
    Dead letter queue item.

    Attributes:
        id: Unique identifier
        operation: Operation that failed
        payload: Operation payload
        error_type: Exception type
        error_message: Error message
        error_details: Additional error details
        status: Current status
        enqueued_at: When item was enqueued
        retry_count: Number of retry attempts
        max_retries: Maximum retry attempts
        next_retry_at: Next retry timestamp
        last_retry_at: Last retry timestamp
        completed_at: When reprocessing completed
        metadata: Additional metadata

    Example:
        ```python
        letter = DeadLetter(
            operation="process_payment",
            payload={"amount": 100, "user_id": "123"},
            error_type="ConnectionError",
            error_message="Database connection failed",
        )
        ```
    """

    operation: str
    payload: dict[str, Any]
    error_type: str
    error_message: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    error_details: dict[str, Any] = field(default_factory=dict)
    status: DeadLetterStatus = DeadLetterStatus.PENDING
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: datetime | None = None
    last_retry_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary.

        Returns:
            Dictionary representation
        """
        data = {
            "id": self.id,
            "operation": self.operation,
            "payload": self.payload,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "error_details": self.error_details,
            "status": self.status.value,
            "enqueued_at": self.enqueued_at.isoformat(),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata,
        }
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeadLetter:
        """
        Create from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            DeadLetter instance
        """
        # Convert status string to enum
        if isinstance(data.get("status"), str):
            data["status"] = DeadLetterStatus(data["status"])

        # Convert timestamp strings to datetime
        for field_name in ["enqueued_at", "next_retry_at", "last_retry_at", "completed_at"]:
            if data.get(field_name) and isinstance(data[field_name], str):
                data[field_name] = datetime.fromisoformat(data[field_name])

        return cls(**data)


class DLQFullError(ResilienceError):
    """
    Dead letter queue full error.

    Raised when the dead letter queue reaches capacity.
    """

    def __init__(
        self,
        message: str = "Dead letter queue is full",
        *,
        current_size: int,
        max_size: int,
        operation: str | None = None,
    ) -> None:
        """
        Initialize DLQ full error.

        Args:
            message: Error message
            current_size: Current queue size
            max_size: Maximum queue size
            operation: Operation name
        """
        self.current_size = current_size
        self.max_size = max_size

        super().__init__(
            message=message,
            operation=operation,
            component="dead_letter_queue",
            details={
                "current_size": current_size,
                "max_size": max_size,
            },
            suggestions=[
                "Process items from the dead letter queue",
                "Increase queue size limit",
                "Review failure patterns",
            ],
        )


class DLQManager:
    """
    Dead letter queue manager.

    Manages failed operations with retry scheduling, monitoring,
    and alerting capabilities.

    Attributes:
        max_queue_size: Maximum queue size
        default_max_retries: Default maximum retries per item
        alert_threshold: Alert when queue size exceeds this
        ttl_days: Time-to-live for items in days

    Example:
        ```python
        # Create DLQ manager
        dlq = DLQManager(
            max_queue_size=10000,
            default_max_retries=3,
            alert_threshold=100,
        )

        # Enqueue failed item
        await dlq.enqueue(
            operation="send_email",
            payload={"to": "user@example.com"},
            error=smtp_error,
            security_context=context,
        )

        # Get statistics
        stats = await dlq.get_statistics(security_context=context)

        # List items for operation
        items = await dlq.list_items(
            operation="send_email",
            status=DeadLetterStatus.PENDING,
            security_context=context,
        )
        ```
    """

    def __init__(
        self,
        max_queue_size: int = 10000,
        default_max_retries: int = 3,
        alert_threshold: int = 100,
        ttl_days: int = 30,
    ) -> None:
        """
        Initialize DLQ manager.

        Args:
            max_queue_size: Maximum queue size
            default_max_retries: Default max retries per item
            alert_threshold: Alert threshold for queue size
            ttl_days: Time-to-live for items in days

        Raises:
            ValidationError: If parameters are invalid
        """
        if max_queue_size < 1:
            raise ValidationError(
                message=f"max_queue_size must be at least 1, got {max_queue_size}",
                field_name="max_queue_size",
            )

        if default_max_retries < 0:
            raise ValidationError(
                message=f"default_max_retries cannot be negative, got {default_max_retries}",
                field_name="default_max_retries",
            )

        self.max_queue_size = max_queue_size
        self.default_max_retries = default_max_retries
        self.alert_threshold = alert_threshold
        self.ttl_days = ttl_days

        # Storage
        self._queues: dict[str, list[DeadLetter]] = defaultdict(list)
        self._items_by_id: dict[str, DeadLetter] = {}
        self._lock = asyncio.Lock()

        # Metrics
        self._total_enqueued = 0
        self._total_dequeued = 0
        self._total_completed = 0
        self._total_failed = 0

    async def enqueue(
        self,
        operation: str,
        payload: dict[str, Any],
        error: Exception,
        security_context: SecurityContext,
        max_retries: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Enqueue a failed operation.

        Args:
            operation: Operation name
            payload: Operation payload
            error: Exception that caused failure
            security_context: Security context
            max_retries: Maximum retry attempts (uses default if None)
            metadata: Additional metadata

        Returns:
            Dead letter ID

        Raises:
            DLQFullError: If queue is full

        Example:
            ```python
            try:
                await process_order(order_data)
            except Exception as e:
                dlq_id = await dlq.enqueue(
                    operation="process_order",
                    payload=order_data,
                    error=e,
                    security_context=context,
                )
                logger.error(f"Order processing failed, DLQ ID: {dlq_id}")
            ```
        """
        security_context.require_permission("resilience.write_dead_letter")

        async with self._lock:
            # Check queue size
            total_items = sum(len(q) for q in self._queues.values())
            if total_items >= self.max_queue_size:
                raise DLQFullError(
                    current_size=total_items,
                    max_size=self.max_queue_size,
                    operation=operation,
                )

            # Create dead letter
            letter = DeadLetter(
                operation=operation,
                payload=payload,
                error_type=type(error).__name__,
                error_message=str(error),
                error_details={
                    "traceback": getattr(error, "__traceback__", None),
                },
                max_retries=max_retries or self.default_max_retries,
                metadata=metadata or {},
            )

            # Add to queue
            self._queues[operation].append(letter)
            self._items_by_id[letter.id] = letter
            self._total_enqueued += 1

            logger.warning(
                f"Enqueued failed operation '{operation}' to DLQ",
                extra={
                    "operation": operation,
                    "dlq_id": letter.id,
                    "error_type": letter.error_type,
                    "queue_size": len(self._queues[operation]),
                },
            )

            # Check alert threshold
            if total_items + 1 >= self.alert_threshold:
                logger.error(
                    f"DLQ size ({total_items + 1}) exceeds alert threshold ({self.alert_threshold})",
                    extra={
                        "total_items": total_items + 1,
                        "alert_threshold": self.alert_threshold,
                    },
                )

            return letter.id

    async def dequeue(
        self,
        operation: str,
        security_context: SecurityContext,
        status_filter: DeadLetterStatus | None = None,
    ) -> DeadLetter | None:
        """
        Dequeue an item for reprocessing.

        Args:
            operation: Operation name
            security_context: Security context
            status_filter: Optional status filter

        Returns:
            Dead letter or None if queue is empty

        Example:
            ```python
            # Dequeue next pending item
            item = await dlq.dequeue(
                operation="process_order",
                security_context=context,
                status_filter=DeadLetterStatus.PENDING,
            )

            if item:
                try:
                    await process_order(item.payload)
                    await dlq.mark_completed(item.id, security_context)
                except Exception as e:
                    await dlq.mark_failed(item.id, e, security_context)
            ```
        """
        security_context.require_permission("resilience.write_dead_letter")

        async with self._lock:
            queue = self._queues.get(operation, [])
            if not queue:
                return None

            # Find first matching item
            for i, letter in enumerate(queue):
                # Check status filter
                if status_filter and letter.status != status_filter:
                    continue

                # Check if ready for retry
                if letter.next_retry_at and datetime.now(UTC) < letter.next_retry_at:
                    continue

                # Check if abandoned
                if letter.retry_count >= letter.max_retries:
                    letter.status = DeadLetterStatus.ABANDONED
                    continue

                # Dequeue item
                letter.status = DeadLetterStatus.REPROCESSING
                letter.last_retry_at = datetime.now(UTC)
                letter.retry_count += 1
                self._total_dequeued += 1

                logger.info(
                    "Dequeued item from DLQ for reprocessing",
                    extra={
                        "operation": operation,
                        "dlq_id": letter.id,
                        "retry_count": letter.retry_count,
                    },
                )

                return letter

            return None

    async def peek(
        self,
        operation: str,
        security_context: SecurityContext,
        status_filter: DeadLetterStatus | None = None,
    ) -> DeadLetter | None:
        """
        Peek at next item without dequeuing.

        Args:
            operation: Operation name
            security_context: Security context
            status_filter: Optional status filter

        Returns:
            Dead letter or None if queue is empty

        Example:
            ```python
            # Peek at next item
            item = await dlq.peek(
                operation="process_order",
                security_context=context,
            )

            if item:
                print(f"Next retry at: {item.next_retry_at}")
            ```
        """
        security_context.require_permission("resilience.read_dead_letter")

        async with self._lock:
            queue = self._queues.get(operation, [])
            if not queue:
                return None

            # Find first matching item
            for letter in queue:
                if status_filter and letter.status != status_filter:
                    continue
                return letter

            return None

    async def mark_completed(
        self,
        dlq_id: str,
        security_context: SecurityContext,
    ) -> None:
        """
        Mark item as completed.

        Args:
            dlq_id: Dead letter ID
            security_context: Security context

        Example:
            ```python
            await dlq.mark_completed(
                dlq_id="abc-123",
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.write_dead_letter")

        async with self._lock:
            letter = self._items_by_id.get(dlq_id)
            if not letter:
                return

            letter.status = DeadLetterStatus.COMPLETED
            letter.completed_at = datetime.now(UTC)
            self._total_completed += 1

            logger.info(
                "Marked DLQ item as completed",
                extra={
                    "operation": letter.operation,
                    "dlq_id": dlq_id,
                },
            )

    async def mark_failed(
        self,
        dlq_id: str,
        error: Exception,
        security_context: SecurityContext,
        retry_delay_seconds: int | None = None,
    ) -> None:
        """
        Mark item as failed and schedule retry.

        Args:
            dlq_id: Dead letter ID
            error: Exception that caused failure
            security_context: Security context
            retry_delay_seconds: Delay before next retry

        Example:
            ```python
            await dlq.mark_failed(
                dlq_id="abc-123",
                error=connection_error,
                retry_delay_seconds=300,
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.write_dead_letter")

        async with self._lock:
            letter = self._items_by_id.get(dlq_id)
            if not letter:
                return

            # Update error details
            letter.error_message = str(error)
            letter.error_type = type(error).__name__

            # Check if max retries exceeded
            if letter.retry_count >= letter.max_retries:
                letter.status = DeadLetterStatus.ABANDONED
                logger.warning(
                    f"DLQ item abandoned after {letter.retry_count} retries",
                    extra={
                        "operation": letter.operation,
                        "dlq_id": dlq_id,
                    },
                )
            else:
                # Schedule retry
                letter.status = DeadLetterStatus.PENDING
                if retry_delay_seconds:
                    letter.next_retry_at = datetime.now(UTC) + timedelta(
                        seconds=retry_delay_seconds
                    )

            self._total_failed += 1

    async def list_items(
        self,
        security_context: SecurityContext,
        operation: str | None = None,
        status: DeadLetterStatus | None = None,
        limit: int | None = None,
    ) -> list[DeadLetter]:
        """
        List dead letter items.

        Args:
            operation: Optional operation filter
            status: Optional status filter
            limit: Maximum number of items to return
            security_context: Security context

        Returns:
            List of dead letters

        Example:
            ```python
            # List all pending items
            items = await dlq.list_items(
                status=DeadLetterStatus.PENDING,
                limit=10,
                security_context=context,
            )

            # List items for specific operation
            items = await dlq.list_items(
                operation="send_email",
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.read_dead_letter")

        async with self._lock:
            items = []

            if operation:
                queues = {operation: self._queues.get(operation, [])}
            else:
                queues = self._queues

            for op, queue in queues.items():
                for letter in queue:
                    if status and letter.status != status:
                        continue
                    items.append(letter)

                    if limit and len(items) >= limit:
                        return items

            return items

    async def get_statistics(
        self,
        security_context: SecurityContext,
    ) -> dict[str, Any]:
        """
        Get DLQ statistics.

        Args:
            security_context: Security context

        Returns:
            Statistics dictionary

        Example:
            ```python
            stats = await dlq.get_statistics(security_context=context)
            print(f"Total items: {stats['total_items']}")
            print(f"Pending: {stats['by_status']['pending']}")
            ```
        """
        security_context.require_permission("resilience.read_dead_letter")

        async with self._lock:
            total_items = sum(len(q) for q in self._queues.values())

            # Count by status
            by_status = defaultdict(int)
            by_operation = defaultdict(int)

            for operation, queue in self._queues.items():
                by_operation[operation] = len(queue)
                for letter in queue:
                    by_status[letter.status.value] += 1

            return {
                "total_items": total_items,
                "total_enqueued": self._total_enqueued,
                "total_dequeued": self._total_dequeued,
                "total_completed": self._total_completed,
                "total_failed": self._total_failed,
                "by_status": dict(by_status),
                "by_operation": dict(by_operation),
                "max_queue_size": self.max_queue_size,
                "alert_threshold": self.alert_threshold,
            }

    async def cleanup_expired(
        self,
        security_context: SecurityContext,
    ) -> int:
        """
        Remove expired items from queue.

        Args:
            security_context: Security context

        Returns:
            Number of items removed

        Example:
            ```python
            removed = await dlq.cleanup_expired(security_context=context)
            print(f"Removed {removed} expired items")
            ```
        """
        security_context.require_permission("resilience.write_dead_letter")

        async with self._lock:
            cutoff = datetime.now(UTC) - timedelta(days=self.ttl_days)
            removed = 0

            for operation, queue in list(self._queues.items()):
                original_len = len(queue)
                self._queues[operation] = [
                    letter for letter in queue if letter.enqueued_at > cutoff
                ]
                removed += original_len - len(self._queues[operation])

                # Remove operation if queue is empty
                if not self._queues[operation]:
                    del self._queues[operation]

            logger.info(f"Cleaned up {removed} expired DLQ items")
            return removed
