"""
Reprocessor for dead letter queue items.

This module provides reprocessing capabilities for failed operations,
with support for various reprocessing strategies.

Example:
    ```python
    from yoda_foundation.resilience.dead_letter import (
        Reprocessor,
        ReprocessingStrategy,
        DLQManager,
    )
    from yoda_foundation.security import create_security_context

    # Create reprocessor
    dlq = DLQManager()
    reprocessor = Reprocessor(
        dlq_manager=dlq,
        default_strategy=ReprocessingStrategy.SEQUENTIAL,
    )

    # Define reprocessing function
    async def process_order(payload: dict):
        # Process the order
        return {"status": "success"}

    # Register handler
    reprocessor.register_handler(
        operation="process_order",
        handler=process_order,
    )

    # Reprocess failed items
    results = await reprocessor.reprocess(
        operation="process_order",
        max_items=10,
        security_context=context,
    )

    print(f"Successes: {results.success_count}")
    print(f"Failures: {results.failure_count}")
    ```
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from yoda_foundation.exceptions import (
    ValidationError,
)
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.security.context import SecurityContext


if TYPE_CHECKING:
    from yoda_foundation.resilience.dead_letter.dlq_manager import (
        DeadLetter,
        DLQManager,
    )

logger = logging.getLogger(__name__)


class ReprocessingStrategy(Enum):
    """Reprocessing strategy for dead letter queue items."""

    SEQUENTIAL = "sequential"  # Process items one at a time
    PARALLEL = "parallel"  # Process items in parallel
    BATCH = "batch"  # Process items in batches


@dataclass
class ReprocessingResult:
    """
    Result of reprocessing operation.

    Attributes:
        operation: Operation name
        total_items: Total items attempted
        success_count: Number of successful reprocessings
        failure_count: Number of failed reprocessings
        skipped_count: Number of skipped items
        results: Individual results by item ID
        started_at: When reprocessing started
        completed_at: When reprocessing completed
        duration_seconds: Total duration

    Example:
        ```python
        result = ReprocessingResult(
            operation="process_order",
            total_items=10,
            success_count=8,
            failure_count=2,
            skipped_count=0,
        )

        print(f"Success rate: {result.success_rate}%")
        ```
    """

    operation: str
    total_items: int
    success_count: int = 0
    failure_count: int = 0
    skipped_count: int = 0
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        """
        Calculate success rate.

        Returns:
            Success rate as percentage (0-100)
        """
        if self.total_items == 0:
            return 0.0
        return (self.success_count / self.total_items) * 100

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "operation": self.operation,
            "total_items": self.total_items,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "skipped_count": self.skipped_count,
            "success_rate": self.success_rate,
            "results": self.results,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
        }


# Type alias for reprocessing handler
ReprocessingHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class Reprocessor:
    """
    Dead letter queue reprocessor.

    Manages reprocessing of failed operations from the dead letter queue
    with support for various processing strategies.

    Attributes:
        dlq_manager: DLQ manager instance
        default_strategy: Default reprocessing strategy
        max_concurrent: Maximum concurrent reprocessing (for parallel strategy)
        batch_size: Batch size (for batch strategy)

    Example:
        ```python
        # Create reprocessor
        reprocessor = Reprocessor(
            dlq_manager=dlq,
            default_strategy=ReprocessingStrategy.PARALLEL,
            max_concurrent=5,
        )

        # Register handlers
        async def handle_order(payload: dict):
            return await process_order(payload["order_id"])

        reprocessor.register_handler("process_order", handle_order)

        # Reprocess failed items
        results = await reprocessor.reprocess(
            operation="process_order",
            max_items=100,
            security_context=context,
        )
        ```
    """

    def __init__(
        self,
        dlq_manager: DLQManager,
        default_strategy: ReprocessingStrategy = ReprocessingStrategy.SEQUENTIAL,
        max_concurrent: int = 5,
        batch_size: int = 10,
    ) -> None:
        """
        Initialize reprocessor.

        Args:
            dlq_manager: DLQ manager instance
            default_strategy: Default reprocessing strategy
            max_concurrent: Maximum concurrent reprocessing
            batch_size: Batch size for batch strategy

        Raises:
            ValidationError: If parameters are invalid
        """
        if max_concurrent < 1:
            raise ValidationError(
                message=f"max_concurrent must be at least 1, got {max_concurrent}",
                field_name="max_concurrent",
            )

        if batch_size < 1:
            raise ValidationError(
                message=f"batch_size must be at least 1, got {batch_size}",
                field_name="batch_size",
            )

        self.dlq_manager = dlq_manager
        self.default_strategy = default_strategy
        self.max_concurrent = max_concurrent
        self.batch_size = batch_size

        # Handler registry
        self._handlers: dict[str, ReprocessingHandler] = {}

    def register_handler(
        self,
        operation: str,
        handler: ReprocessingHandler,
    ) -> None:
        """
        Register reprocessing handler for operation.

        Args:
            operation: Operation name
            handler: Async function to handle reprocessing

        Example:
            ```python
            async def handle_email(payload: dict):
                await send_email(
                    to=payload["to"],
                    subject=payload["subject"],
                    body=payload["body"],
                )

            reprocessor.register_handler("send_email", handle_email)
            ```
        """
        self._handlers[operation] = handler

        logger.info(
            f"Registered reprocessing handler for operation '{operation}'",
            extra={"operation": operation},
        )

    def unregister_handler(self, operation: str) -> None:
        """
        Unregister reprocessing handler.

        Args:
            operation: Operation name

        Example:
            ```python
            reprocessor.unregister_handler("send_email")
            ```
        """
        if operation in self._handlers:
            del self._handlers[operation]
            logger.info(
                f"Unregistered reprocessing handler for operation '{operation}'",
                extra={"operation": operation},
            )

    async def reprocess(
        self,
        operation: str,
        security_context: SecurityContext,
        max_items: int | None = None,
        strategy: ReprocessingStrategy | None = None,
    ) -> ReprocessingResult:
        """
        Reprocess failed items for operation.

        Args:
            operation: Operation name
            security_context: Security context
            max_items: Maximum items to reprocess
            strategy: Reprocessing strategy (uses default if not provided)

        Returns:
            Reprocessing result

        Raises:
            ValidationError: If handler not registered

        Example:
            ```python
            # Reprocess up to 50 items sequentially
            results = await reprocessor.reprocess(
                operation="process_order",
                max_items=50,
                strategy=ReprocessingStrategy.SEQUENTIAL,
                security_context=context,
            )

            if results.failure_count > 0:
                logger.warning(f"{results.failure_count} items still failing")
            ```
        """
        security_context.require_permission("resilience.write_dead_letter")

        # Validate handler is registered
        if operation not in self._handlers:
            raise ValidationError(
                message=f"No handler registered for operation '{operation}'",
                field_name="operation",
            )

        strategy = strategy or self.default_strategy

        # Get items to reprocess
        items = await self.dlq_manager.list_items(
            security_context=security_context,
            operation=operation,
            limit=max_items,
        )

        if not items:
            logger.info(f"No items to reprocess for operation '{operation}'")
            return ReprocessingResult(
                operation=operation,
                total_items=0,
            )

        # Initialize result
        result = ReprocessingResult(
            operation=operation,
            total_items=len(items),
            started_at=datetime.now(UTC),
        )

        logger.info(
            f"Starting reprocessing of {len(items)} items for '{operation}' using {strategy.value} strategy",
            extra={
                "operation": operation,
                "total_items": len(items),
                "strategy": strategy.value,
            },
        )

        # Execute reprocessing based on strategy
        if strategy == ReprocessingStrategy.SEQUENTIAL:
            await self._reprocess_sequential(items, result, security_context)
        elif strategy == ReprocessingStrategy.PARALLEL:
            await self._reprocess_parallel(items, result, security_context)
        elif strategy == ReprocessingStrategy.BATCH:
            await self._reprocess_batch(items, result, security_context)

        # Finalize result
        result.completed_at = datetime.now(UTC)
        result.duration_seconds = (result.completed_at - result.started_at).total_seconds()

        logger.info(
            f"Reprocessing completed for '{operation}'",
            extra={
                "operation": operation,
                "total_items": result.total_items,
                "success_count": result.success_count,
                "failure_count": result.failure_count,
                "duration_seconds": result.duration_seconds,
                "success_rate": result.success_rate,
            },
        )

        return result

    async def _reprocess_sequential(
        self,
        items: list[DeadLetter],
        result: ReprocessingResult,
        security_context: SecurityContext,
    ) -> None:
        """
        Reprocess items sequentially.

        Args:
            items: Items to reprocess
            result: Result object to update
            security_context: Security context
        """
        for item in items:
            await self._reprocess_item(item, result, security_context)

    async def _reprocess_parallel(
        self,
        items: list[DeadLetter],
        result: ReprocessingResult,
        security_context: SecurityContext,
    ) -> None:
        """
        Reprocess items in parallel.

        Args:
            items: Items to reprocess
            result: Result object to update
            security_context: Security context
        """
        # Process in chunks to limit concurrency
        for i in range(0, len(items), self.max_concurrent):
            chunk = items[i : i + self.max_concurrent]
            tasks = [self._reprocess_item(item, result, security_context) for item in chunk]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _reprocess_batch(
        self,
        items: list[DeadLetter],
        result: ReprocessingResult,
        security_context: SecurityContext,
    ) -> None:
        """
        Reprocess items in batches.

        Args:
            items: Items to reprocess
            result: Result object to update
            security_context: Security context
        """
        # Process in batches
        for i in range(0, len(items), self.batch_size):
            batch = items[i : i + self.batch_size]
            tasks = [self._reprocess_item(item, result, security_context) for item in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _reprocess_item(
        self,
        item: DeadLetter,
        result: ReprocessingResult,
        security_context: SecurityContext,
    ) -> None:
        """
        Reprocess a single item.

        Args:
            item: Dead letter item
            result: Result object to update
            security_context: Security context
        """
        handler = self._handlers.get(item.operation)
        if not handler:
            logger.warning(
                f"No handler for operation '{item.operation}'",
                extra={"operation": item.operation, "dlq_id": item.id},
            )
            result.skipped_count += 1
            result.results[item.id] = {
                "status": "skipped",
                "reason": "No handler registered",
            }
            return

        try:
            # Dequeue item
            dequeued_item = await self.dlq_manager.dequeue(
                operation=item.operation,
                security_context=security_context,
            )

            if not dequeued_item or dequeued_item.id != item.id:
                logger.warning(
                    f"Failed to dequeue item {item.id}",
                    extra={"operation": item.operation, "dlq_id": item.id},
                )
                result.skipped_count += 1
                result.results[item.id] = {
                    "status": "skipped",
                    "reason": "Failed to dequeue",
                }
                return

            # Execute handler
            handler_result = await handler(dequeued_item.payload)

            # Mark as completed
            await self.dlq_manager.mark_completed(
                dlq_id=dequeued_item.id,
                security_context=security_context,
            )

            result.success_count += 1
            result.results[item.id] = {
                "status": "success",
                "result": handler_result,
            }

            logger.debug(
                f"Successfully reprocessed item {item.id}",
                extra={"operation": item.operation, "dlq_id": item.id},
            )

        except (
            AgenticBaseException,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
        ) as e:
            # Mark as failed
            await self.dlq_manager.mark_failed(
                dlq_id=item.id,
                error=e,
                security_context=security_context,
                retry_delay_seconds=300,  # 5 minutes
            )

            result.failure_count += 1
            result.results[item.id] = {
                "status": "failure",
                "error": str(e),
                "error_type": type(e).__name__,
            }

            logger.error(
                f"Failed to reprocess item {item.id}: {e!s}",
                extra={
                    "operation": item.operation,
                    "dlq_id": item.id,
                    "error": str(e),
                },
            )

    async def reprocess_all(
        self,
        security_context: SecurityContext,
        max_items_per_operation: int | None = None,
    ) -> dict[str, ReprocessingResult]:
        """
        Reprocess all operations with registered handlers.

        Args:
            security_context: Security context
            max_items_per_operation: Max items per operation

        Returns:
            Dictionary mapping operation to reprocessing result

        Example:
            ```python
            # Reprocess all operations
            results = await reprocessor.reprocess_all(
                max_items_per_operation=50,
                security_context=context,
            )

            for operation, result in results.items():
                print(f"{operation}: {result.success_count}/{result.total_items} succeeded")
            ```
        """
        security_context.require_permission("resilience.write_dead_letter")

        results = {}

        for operation in self._handlers.keys():
            try:
                result = await self.reprocess(
                    operation=operation,
                    max_items=max_items_per_operation,
                    security_context=security_context,
                )
                results[operation] = result
            except (
                AgenticBaseException,
                ConnectionError,
                TimeoutError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
                RuntimeError,
            ) as e:
                logger.error(
                    f"Failed to reprocess operation '{operation}': {e!s}",
                    extra={"operation": operation, "error": str(e)},
                )

        return results

    async def get_reprocessing_stats(
        self,
        security_context: SecurityContext,
    ) -> dict[str, Any]:
        """
        Get reprocessing statistics.

        Args:
            security_context: Security context

        Returns:
            Statistics dictionary

        Example:
            ```python
            stats = await reprocessor.get_reprocessing_stats(
                security_context=context,
            )

            print(f"Registered handlers: {stats['registered_handlers']}")
            ```
        """
        security_context.require_permission("resilience.read_dead_letter")

        # Get DLQ stats
        dlq_stats = await self.dlq_manager.get_statistics(
            security_context=security_context,
        )

        # Count items per registered operation
        items_by_operation: dict[str, int] = defaultdict(int)
        for operation in self._handlers.keys():
            items = await self.dlq_manager.list_items(
                security_context=security_context,
                operation=operation,
            )
            items_by_operation[operation] = len(items)

        return {
            "registered_handlers": list(self._handlers.keys()),
            "total_registered": len(self._handlers),
            "items_by_operation": dict(items_by_operation),
            "total_pending_items": sum(items_by_operation.values()),
            "dlq_stats": dlq_stats,
        }
