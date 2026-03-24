"""
Semaphore-based bulkhead implementation.

This module provides a semaphore-based bulkhead for resource isolation
with queue management and timeout support.

Example:
    ```python
    from yoda_foundation.resilience.bulkhead import SemaphoreBulkhead

    # Create semaphore bulkhead
    bulkhead = SemaphoreBulkhead(
        name="database_connections",
        max_concurrent=10,
        max_queue_size=50,
        queue_timeout_ms=5000,
    )

    # Execute with protection
    result = await bulkhead.execute(
        func=db_query,
        security_context=context,
    )

    # Or use context manager
    async with bulkhead.acquire(security_context=context):
        result = await db_query()
    ```
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from yoda_foundation.resilience.bulkhead.bulkhead import (
    Bulkhead,
    BulkheadConfig,
    BulkheadRejectedException,
    BulkheadRejectionReason,
)
from yoda_foundation.security.context import SecurityContext


logger = logging.getLogger(__name__)


@dataclass
class QueuedRequest:
    """
    Represents a queued request in the bulkhead.

    Attributes:
        request_id: Unique request identifier.
        enqueued_at: When the request was enqueued.
        timeout_at: When the request will timeout.
        event: Event to signal when permit is available.
        granted: Whether the permit was granted.

    Example:
        ```python
        request = QueuedRequest(
            request_id="req_123",
            enqueued_at=datetime.now(timezone.utc),
            timeout_at=datetime.now(timezone.utc) + timedelta(seconds=5),
            event=asyncio.Event(),
        )
        ```
    """

    request_id: str
    enqueued_at: datetime
    timeout_at: datetime
    event: asyncio.Event = field(default_factory=asyncio.Event)
    granted: bool = False

    @property
    def wait_time_ms(self) -> float:
        """Get time spent waiting in queue."""
        return (datetime.now(UTC) - self.enqueued_at).total_seconds() * 1000

    @property
    def is_expired(self) -> bool:
        """Check if request has timed out."""
        return datetime.now(UTC) >= self.timeout_at


class SemaphoreBulkhead(Bulkhead):
    """
    Semaphore-based bulkhead implementation.

    Uses asyncio.Semaphore for concurrency limiting with an optional
    queue for excess requests.

    Attributes:
        name: Bulkhead name.
        max_concurrent: Maximum concurrent requests allowed.
        max_queue_size: Maximum queue size for waiting requests.
        queue_timeout_ms: Timeout for queued requests in milliseconds.
        _fair_queuing: Whether to use FIFO ordering for queued requests.

    Example:
        ```python
        # Create bulkhead with queue
        bulkhead = SemaphoreBulkhead(
            name="api_calls",
            max_concurrent=10,
            max_queue_size=50,
            queue_timeout_ms=5000,
        )

        # Execute with bulkhead protection
        try:
            result = await bulkhead.execute(
                func=api_call,
                security_context=context,
            )
        except BulkheadRejectedException as e:
            logger.warning(f"Request rejected: {e}")
            # Handle rejection (use fallback, return error, etc.)

        # Check queue status
        stats = await bulkhead.get_statistics(security_context=context)
        print(f"Queue size: {stats.queue_size}/{stats.max_queue_size}")
        ```
    """

    def __init__(
        self,
        name: str = "default",
        max_concurrent: int = 10,
        max_queue_size: int = 0,
        queue_timeout_ms: int = 30000,
        fair_queuing: bool = True,
    ) -> None:
        """
        Initialize semaphore bulkhead.

        Args:
            name: Bulkhead name
            max_concurrent: Maximum concurrent requests
            max_queue_size: Maximum queue size (0 = no queue)
            queue_timeout_ms: Timeout for queued requests in milliseconds
            fair_queuing: Whether to use FIFO ordering for queued requests

        Example:
            ```python
            bulkhead = SemaphoreBulkhead(
                name="database",
                max_concurrent=20,
                max_queue_size=100,
                queue_timeout_ms=10000,
            )
            ```
        """
        config = BulkheadConfig(
            name=name,
            max_concurrent=max_concurrent,
            max_queue_size=max_queue_size,
            queue_timeout_ms=queue_timeout_ms,
        )
        super().__init__(config=config)

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_count = 0
        self._queue: deque[QueuedRequest] = deque()
        self._fair_queuing = fair_queuing
        self._request_counter = 0
        self._queue_lock = asyncio.Lock()

    async def _acquire_internal(
        self,
        timeout_ms: int | None = None,
    ) -> bool:
        """
        Acquire semaphore permit with optional queueing.

        Attempts to acquire a semaphore permit within the specified timeout.
        If the semaphore is at capacity and queueing is enabled, the request
        will wait in the queue. Raises BulkheadRejectedException if the queue
        is full or no queueing is configured.

        Args:
            timeout_ms: Timeout in milliseconds for acquisition.

        Returns:
            True if permit acquired successfully, False on timeout.

        Raises:
            BulkheadRejectedException: If queue is full or no queue configured.
        """
        effective_timeout = timeout_ms or self.config.queue_timeout_ms
        timeout_seconds = effective_timeout / 1000.0

        # Try immediate acquisition
        if self._semaphore.locked():
            # Semaphore is full, check if we can queue
            async with self._queue_lock:
                if (
                    self.config.max_queue_size > 0
                    and len(self._queue) >= self.config.max_queue_size
                ):
                    # Queue is full
                    async with self._lock:
                        self._rejected_requests += 1

                    raise BulkheadRejectedException(
                        bulkhead_name=self.config.name,
                        rejection_reason=BulkheadRejectionReason.QUEUE_FULL,
                        current_active=self._active_count,
                        max_concurrent=self.config.max_concurrent,
                        queue_size=len(self._queue),
                        max_queue_size=self.config.max_queue_size,
                    )

                if self.config.max_queue_size == 0:
                    # No queue configured, reject immediately
                    async with self._lock:
                        self._rejected_requests += 1

                    raise BulkheadRejectedException(
                        bulkhead_name=self.config.name,
                        rejection_reason=BulkheadRejectionReason.MAX_CONCURRENT_REACHED,
                        current_active=self._active_count,
                        max_concurrent=self.config.max_concurrent,
                        queue_size=0,
                        max_queue_size=0,
                    )

        # Try to acquire with timeout
        try:
            acquired = await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=timeout_seconds,
            )

            if acquired:
                async with self._queue_lock:
                    self._active_count += 1

                logger.debug(
                    f"Bulkhead '{self.config.name}' permit acquired. "
                    f"Active: {self._active_count}/{self.config.max_concurrent}",
                    extra={
                        "bulkhead_name": self.config.name,
                        "active_count": self._active_count,
                    },
                )

            return acquired

        except TimeoutError:
            async with self._lock:
                self._timed_out_requests += 1

            logger.warning(
                f"Bulkhead '{self.config.name}' acquire timed out after {effective_timeout}ms",
                extra={
                    "bulkhead_name": self.config.name,
                    "timeout_ms": effective_timeout,
                },
            )
            return False

    async def _release_internal(self) -> None:
        """
        Release semaphore permit.

        Decrements the active count and releases the semaphore to allow
        another waiting request to proceed. Logs the release operation
        with current active count.
        """
        async with self._queue_lock:
            if self._active_count > 0:
                self._active_count -= 1
                self._semaphore.release()

                logger.debug(
                    f"Bulkhead '{self.config.name}' permit released. "
                    f"Active: {self._active_count}/{self.config.max_concurrent}",
                    extra={
                        "bulkhead_name": self.config.name,
                        "active_count": self._active_count,
                    },
                )

    async def _get_active_count(self) -> int:
        """
        Get current number of active requests.

        Returns:
            Number of requests currently holding semaphore permits.
        """
        return self._active_count

    async def _get_queue_size(self) -> int:
        """
        Get current queue size.

        Returns:
            Number of requests waiting in the queue.
        """
        return len(self._queue)

    async def try_acquire(
        self,
        security_context: SecurityContext,
    ) -> bool:
        """
        Try to acquire permit without waiting.

        Args:
            security_context: Security context

        Returns:
            True if permit acquired immediately, False otherwise

        Example:
            ```python
            if await bulkhead.try_acquire(security_context=context):
                try:
                    await protected_operation()
                finally:
                    await bulkhead.release(security_context=context)
            else:
                # Handle rejection
                await use_fallback()
            ```
        """
        if not self.config.enabled:
            return True

        async with self._lock:
            self._total_requests += 1

        # Try immediate acquisition (no waiting)
        if not self._semaphore.locked():
            try:
                # Use wait_for with 0 timeout for non-blocking acquire
                acquired = await asyncio.wait_for(
                    self._semaphore.acquire(),
                    timeout=0.0,
                )

                if acquired:
                    async with self._queue_lock:
                        self._active_count += 1
                    return True

            except TimeoutError:
                pass

        async with self._lock:
            self._rejected_requests += 1

        return False

    async def get_queue_info(
        self,
        security_context: SecurityContext,
    ) -> dict:
        """
        Get detailed queue information.

        Args:
            security_context: Security context

        Returns:
            Dictionary with queue details

        Example:
            ```python
            queue_info = await bulkhead.get_queue_info(security_context=context)
            print(f"Queue size: {queue_info['size']}")
            print(f"Oldest wait: {queue_info['oldest_wait_ms']}ms")
            ```
        """
        async with self._queue_lock:
            queue_list = list(self._queue)

            oldest_wait_ms = 0.0
            if queue_list:
                oldest_wait_ms = queue_list[0].wait_time_ms

            return {
                "size": len(queue_list),
                "max_size": self.config.max_queue_size,
                "oldest_wait_ms": oldest_wait_ms,
                "fair_queuing": self._fair_queuing,
            }

    async def drain_queue(
        self,
        security_context: SecurityContext,
    ) -> int:
        """
        Drain the queue, rejecting all waiting requests.

        Args:
            security_context: Security context

        Returns:
            Number of requests drained

        Example:
            ```python
            # Clear queue during maintenance
            drained = await bulkhead.drain_queue(security_context=context)
            print(f"Drained {drained} requests from queue")
            ```
        """
        security_context.require_permission("resilience.manage_bulkhead")

        async with self._queue_lock:
            count = len(self._queue)

            # Signal all waiting requests to fail
            while self._queue:
                request = self._queue.popleft()
                request.event.set()

            logger.info(
                f"Bulkhead '{self.config.name}' queue drained: {count} requests",
                extra={"bulkhead_name": self.config.name, "drained_count": count},
            )

            return count

    async def resize(
        self,
        security_context: SecurityContext,
        max_concurrent: int | None = None,
        max_queue_size: int | None = None,
    ) -> None:
        """
        Dynamically resize bulkhead limits.

        Args:
            security_context: Security context
            max_concurrent: New maximum concurrent limit
            max_queue_size: New maximum queue size

        Example:
            ```python
            # Increase capacity during high load
            await bulkhead.resize(
                security_context=context,
                max_concurrent=20,
                max_queue_size=100,
            )
            ```
        """
        security_context.require_permission("resilience.manage_bulkhead")

        async with self._queue_lock:
            if max_concurrent is not None and max_concurrent != self.config.max_concurrent:
                # Resize semaphore
                difference = max_concurrent - self.config.max_concurrent

                if difference > 0:
                    # Increase limit - release additional permits
                    for _ in range(difference):
                        self._semaphore.release()
                else:
                    # Decrease limit - we can't easily reclaim permits
                    # New limit will take effect as permits are released
                    pass

                old_limit = self.config.max_concurrent
                self.config.max_concurrent = max_concurrent

                logger.info(
                    f"Bulkhead '{self.config.name}' max_concurrent: {old_limit} -> {max_concurrent}",
                    extra={
                        "bulkhead_name": self.config.name,
                        "old_limit": old_limit,
                        "new_limit": max_concurrent,
                    },
                )

            if max_queue_size is not None and max_queue_size != self.config.max_queue_size:
                old_queue_size = self.config.max_queue_size
                self.config.max_queue_size = max_queue_size

                # If queue is now too large, we don't evict - just prevent new entries
                logger.info(
                    f"Bulkhead '{self.config.name}' max_queue_size: {old_queue_size} -> {max_queue_size}",
                    extra={
                        "bulkhead_name": self.config.name,
                        "old_queue_size": old_queue_size,
                        "new_queue_size": max_queue_size,
                    },
                )

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"SemaphoreBulkhead("
            f"name={self.config.name}, "
            f"max_concurrent={self.config.max_concurrent}, "
            f"max_queue_size={self.config.max_queue_size}, "
            f"active={self._active_count})"
        )
