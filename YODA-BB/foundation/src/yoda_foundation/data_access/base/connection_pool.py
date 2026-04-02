"""
Connection pool infrastructure for the Agentic AI Component Library.

This module provides a generic async connection pool implementation that can
be used by various connectors to manage connection resources efficiently.

Features:
- Configurable pool sizing (min/max connections)
- Automatic connection health checking
- Connection lifecycle management (acquire, release, eviction)
- Comprehensive statistics and monitoring
- Security context validation for all operations

Example:
    ```python
    from yoda_foundation.data_access.base import (
        ConnectionPool,
        PoolConfig,
        PoolStats,
    )
    from yoda_foundation.security import create_security_context

    # Configure the pool
    config = PoolConfig(
        min_size=2,
        max_size=10,
        acquire_timeout=30.0,
        max_idle_time=300.0,
        health_check_interval=60.0,
    )

    # Create pool with connection factory
    async def create_connection():
        return await asyncpg.connect(...)

    pool = ConnectionPool(config, factory=create_connection)

    # Initialize the pool
    await pool.initialize(security_context)

    # Acquire and use connection
    async with pool.acquire(security_context) as conn:
        result = await conn.fetch("SELECT * FROM users")

    # Get pool statistics
    stats = await pool.get_stats()
    print(f"Active: {stats.active_connections}/{stats.total_connections}")

    # Cleanup
    await pool.close_all()
    ```
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from yoda_foundation.exceptions import (
    AuthorizationError,
    ValidationError,
)
from yoda_foundation.exceptions.base import (
    ErrorSeverity,
)
from yoda_foundation.exceptions.data_access import (
    ConnectionPoolError,
)
from yoda_foundation.security.context import SecurityContext


# =============================================================================
# Type Definitions
# =============================================================================


# Type variable for connection type
ConnectionT = TypeVar("ConnectionT")

# Connection factory type
ConnectionFactory = Callable[[], Coroutine[Any, Any, ConnectionT]]

# Connection validator type
ConnectionValidator = Callable[[ConnectionT], Coroutine[Any, Any, bool]]

# Connection closer type
ConnectionCloser = Callable[[ConnectionT], Coroutine[Any, Any, None]]


class PoolState(Enum):
    """
    Connection pool state.

    States:
    - UNINITIALIZED: Pool not yet initialized
    - INITIALIZING: Pool initialization in progress
    - RUNNING: Pool is operational
    - DRAINING: Pool is shutting down, no new acquisitions
    - CLOSED: Pool is fully closed
    """

    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    RUNNING = "running"
    DRAINING = "draining"
    CLOSED = "closed"


# =============================================================================
# Configuration and Statistics
# =============================================================================


@dataclass
class PoolConfig:
    """
    Configuration for connection pools.

    Provides comprehensive configuration options for pool behavior,
    including sizing, timeouts, and health checking.

    Attributes:
        min_size: Minimum number of connections to maintain
        max_size: Maximum number of connections allowed
        max_idle_time: Maximum time (seconds) a connection can be idle
        acquire_timeout: Timeout (seconds) for acquiring a connection
        health_check_interval: Interval (seconds) between health checks
        max_lifetime: Maximum lifetime (seconds) for a connection
        validation_timeout: Timeout (seconds) for validating connections
        retry_attempts: Number of retry attempts for connection creation
        retry_delay: Delay (seconds) between retry attempts
        enable_overflow: Allow temporary connections beyond max_size
        overflow_max_size: Maximum overflow connections (if enabled)

    Example:
        ```python
        config = PoolConfig(
            min_size=5,
            max_size=20,
            acquire_timeout=10.0,
            health_check_interval=30.0,
            max_lifetime=3600.0,
        )
        ```
    """

    min_size: int = 2
    max_size: int = 10
    max_idle_time: float = 300.0
    acquire_timeout: float = 30.0
    health_check_interval: float = 60.0
    max_lifetime: float = 3600.0
    validation_timeout: float = 5.0
    retry_attempts: int = 3
    retry_delay: float = 0.5
    enable_overflow: bool = False
    overflow_max_size: int = 5

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.min_size < 0:
            raise ValidationError(
                message="min_size must be non-negative",
                field_name="min_size",
                suggestions=["Set min_size to 0 or greater"],
            )

        if self.max_size < 1:
            raise ValidationError(
                message="max_size must be at least 1",
                field_name="max_size",
                suggestions=["Set max_size to at least 1"],
            )

        if self.min_size > self.max_size:
            raise ValidationError(
                message="min_size cannot exceed max_size",
                field_name="min_size",
                suggestions=[f"Set min_size to {self.max_size} or less"],
            )

        if self.acquire_timeout <= 0:
            raise ValidationError(
                message="acquire_timeout must be positive",
                field_name="acquire_timeout",
                suggestions=["Set acquire_timeout to a positive value"],
            )

        if self.max_idle_time < 0:
            raise ValidationError(
                message="max_idle_time must be non-negative",
                field_name="max_idle_time",
                suggestions=["Set max_idle_time to 0 or greater"],
            )


@dataclass
class PoolStats:
    """
    Statistics for connection pool monitoring.

    Provides comprehensive metrics for monitoring pool health,
    utilization, and performance.

    Attributes:
        pool_id: Unique identifier for the pool
        state: Current pool state
        total_connections: Total connections in pool (active + idle)
        active_connections: Connections currently in use
        idle_connections: Available connections
        pending_requests: Requests waiting for connections
        overflow_connections: Temporary overflow connections
        connections_created: Total connections created (lifetime)
        connections_closed: Total connections closed (lifetime)
        acquire_count: Total acquire operations (lifetime)
        release_count: Total release operations (lifetime)
        timeout_count: Total acquire timeouts (lifetime)
        health_check_failures: Total health check failures (lifetime)
        avg_acquire_time_ms: Average acquire time in milliseconds
        max_acquire_time_ms: Maximum acquire time in milliseconds
        pool_utilization: Current utilization percentage (0-100)
        uptime_seconds: Time since pool initialization
        last_health_check_at: Timestamp of last health check
        collected_at: When these stats were collected

    Example:
        ```python
        stats = await pool.get_stats()
        print(f"Pool utilization: {stats.pool_utilization:.1f}%")
        print(f"Active: {stats.active_connections}")
        print(f"Idle: {stats.idle_connections}")
        ```
    """

    pool_id: str
    state: PoolState = PoolState.UNINITIALIZED
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    pending_requests: int = 0
    overflow_connections: int = 0
    connections_created: int = 0
    connections_closed: int = 0
    acquire_count: int = 0
    release_count: int = 0
    timeout_count: int = 0
    health_check_failures: int = 0
    avg_acquire_time_ms: float = 0.0
    max_acquire_time_ms: float = 0.0
    pool_utilization: float = 0.0
    uptime_seconds: float = 0.0
    last_health_check_at: datetime | None = None
    collected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "pool_id": self.pool_id,
            "state": self.state.value,
            "total_connections": self.total_connections,
            "active_connections": self.active_connections,
            "idle_connections": self.idle_connections,
            "pending_requests": self.pending_requests,
            "overflow_connections": self.overflow_connections,
            "connections_created": self.connections_created,
            "connections_closed": self.connections_closed,
            "acquire_count": self.acquire_count,
            "release_count": self.release_count,
            "timeout_count": self.timeout_count,
            "health_check_failures": self.health_check_failures,
            "avg_acquire_time_ms": self.avg_acquire_time_ms,
            "max_acquire_time_ms": self.max_acquire_time_ms,
            "pool_utilization": self.pool_utilization,
            "uptime_seconds": self.uptime_seconds,
            "last_health_check_at": (
                self.last_health_check_at.isoformat() if self.last_health_check_at else None
            ),
            "collected_at": self.collected_at.isoformat(),
        }


# =============================================================================
# Connection Wrapper
# =============================================================================


@dataclass
class PooledConnection(Generic[ConnectionT]):
    """
    Wrapper for pooled connections with metadata.

    Tracks connection lifecycle information for pool management.

    Attributes:
        connection_id: Unique connection identifier
        connection: The actual connection object
        created_at: When the connection was created
        last_used_at: Last time connection was used
        last_validated_at: Last successful health check
        use_count: Number of times connection has been acquired
        is_overflow: Whether this is an overflow connection
    """

    connection_id: str
    connection: ConnectionT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_used_at: datetime | None = None
    last_validated_at: datetime | None = None
    use_count: int = 0
    is_overflow: bool = False

    @property
    def age_seconds(self) -> float:
        """Get connection age in seconds."""
        return (datetime.now(UTC) - self.created_at).total_seconds()

    @property
    def idle_seconds(self) -> float:
        """Get idle time in seconds."""
        if self.last_used_at is None:
            return self.age_seconds
        return (datetime.now(UTC) - self.last_used_at).total_seconds()


# =============================================================================
# Pool-Specific Exceptions
# =============================================================================


class PoolExhaustedError(ConnectionPoolError):
    """
    Raised when pool is exhausted and no connections available.

    Example:
        ```python
        raise PoolExhaustedError(
            pool_size=10,
            active_connections=10,
            pending_requests=5,
        )
        ```
    """

    def __init__(
        self,
        message: str = "Connection pool exhausted",
        *,
        pool_size: int | None = None,
        active_connections: int | None = None,
        pending_requests: int | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize pool exhausted error."""
        details = kwargs.pop("details", {})
        details.update(
            {
                "pool_size": pool_size,
                "active_connections": active_connections,
                "pending_requests": pending_requests,
            }
        )

        super().__init__(
            message=message,
            pool_size=pool_size,
            active_connections=active_connections,
            severity=ErrorSeverity.HIGH,
            retryable=True,
            user_message="Service is busy. Please try again shortly.",
            suggestions=[
                "Retry after a brief delay",
                "Consider increasing pool size",
                "Check for connection leaks",
                "Reduce concurrent operations",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )
        self.pending_requests = pending_requests


class PoolAcquireTimeoutError(ConnectionPoolError):
    """
    Raised when acquire times out waiting for connection.

    Example:
        ```python
        raise PoolAcquireTimeoutError(
            timeout_seconds=30.0,
            pool_size=10,
            active_connections=10,
        )
        ```
    """

    def __init__(
        self,
        message: str = "Timeout waiting for connection",
        *,
        timeout_seconds: float | None = None,
        pool_size: int | None = None,
        active_connections: int | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize acquire timeout error."""
        details = kwargs.pop("details", {})
        details.update(
            {
                "timeout_seconds": timeout_seconds,
                "pool_size": pool_size,
                "active_connections": active_connections,
            }
        )

        suggestions = [
            "Retry the operation",
            "Consider increasing acquire_timeout",
            "Consider increasing pool size",
        ]
        if timeout_seconds:
            suggestions[1] = f"Consider increasing acquire_timeout from {timeout_seconds}s"

        super().__init__(
            message=message,
            pool_size=pool_size,
            active_connections=active_connections,
            severity=ErrorSeverity.MEDIUM,
            retryable=True,
            user_message="Connection temporarily unavailable. Please try again.",
            suggestions=suggestions,
            cause=cause,
            details=details,
            **kwargs,
        )
        self.timeout_seconds = timeout_seconds


class PoolNotInitializedError(ConnectionPoolError):
    """
    Raised when operation attempted on uninitialized pool.

    Example:
        ```python
        raise PoolNotInitializedError(pool_id="pool_abc123")
        ```
    """

    def __init__(
        self,
        message: str = "Connection pool not initialized",
        *,
        pool_id: str | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize not initialized error."""
        details = kwargs.pop("details", {})
        details["pool_id"] = pool_id

        super().__init__(
            message=message,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message="Service not ready. Please try again.",
            suggestions=[
                "Call pool.initialize() before acquiring connections",
                "Ensure pool is properly configured",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )


class PoolClosedError(ConnectionPoolError):
    """
    Raised when operation attempted on closed pool.

    Example:
        ```python
        raise PoolClosedError(pool_id="pool_abc123")
        ```
    """

    def __init__(
        self,
        message: str = "Connection pool is closed",
        *,
        pool_id: str | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize pool closed error."""
        details = kwargs.pop("details", {})
        details["pool_id"] = pool_id

        super().__init__(
            message=message,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
            user_message="Service unavailable.",
            suggestions=[
                "Create a new pool instance",
                "Check service status",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )


# =============================================================================
# Connection Pool Implementation
# =============================================================================


class ConnectionPool(Generic[ConnectionT]):
    """
    Generic async connection pool with comprehensive management.

    Provides efficient connection pooling with automatic health checking,
    connection lifecycle management, and comprehensive monitoring.

    Attributes:
        config: Pool configuration
        pool_id: Unique pool identifier

    Example:
        ```python
        # Define connection factory
        async def create_conn():
            return await asyncpg.connect(dsn=DATABASE_URL)

        # Define validator
        async def validate_conn(conn):
            try:
                await conn.execute("SELECT 1")
                return True
            except (ConnectionError, TimeoutError, OSError):
                return False

        # Define closer
        async def close_conn(conn):
            await conn.close()

        # Create and initialize pool
        config = PoolConfig(min_size=2, max_size=10)
        pool = ConnectionPool(
            config=config,
            factory=create_conn,
            validator=validate_conn,
            closer=close_conn,
        )

        await pool.initialize(security_context)

        # Use connections
        async with pool.acquire(security_context) as conn:
            result = await conn.fetch("SELECT * FROM users")

        # Cleanup
        await pool.close_all()
        ```

    Note:
        - All public methods require a SecurityContext
        - Always call close_all() when done to release resources
        - Use the async context manager (acquire) for automatic release
    """

    # Permission required for pool operations
    PERMISSION_POOL_MANAGE = "data.pool.manage"
    PERMISSION_POOL_ACQUIRE = "data.pool.acquire"

    def __init__(
        self,
        config: PoolConfig,
        factory: ConnectionFactory[ConnectionT],
        validator: ConnectionValidator[ConnectionT] | None = None,
        closer: ConnectionCloser[ConnectionT] | None = None,
    ) -> None:
        """
        Initialize the connection pool.

        Args:
            config: Pool configuration
            factory: Async function to create new connections
            validator: Optional async function to validate connections
            closer: Optional async function to close connections

        Example:
            ```python
            pool = ConnectionPool(
                config=PoolConfig(min_size=2, max_size=10),
                factory=create_connection,
                validator=validate_connection,
                closer=close_connection,
            )
            ```
        """
        self._config = config
        self._factory = factory
        self._validator = validator
        self._closer = closer

        self._pool_id = f"pool_{uuid.uuid4().hex[:12]}"
        self._state = PoolState.UNINITIALIZED
        self._initialized_at: datetime | None = None

        # Connection storage
        self._idle_connections: deque[PooledConnection[ConnectionT]] = deque()
        self._active_connections: set[str] = set()
        self._all_connections: dict[str, PooledConnection[ConnectionT]] = {}
        self._overflow_connections: set[str] = set()

        # Synchronization
        self._lock = asyncio.Lock()
        self._available = asyncio.Condition(self._lock)
        self._pending_count = 0

        # Statistics
        self._stats_acquire_count = 0
        self._stats_release_count = 0
        self._stats_timeout_count = 0
        self._stats_health_check_failures = 0
        self._stats_connections_created = 0
        self._stats_connections_closed = 0
        self._stats_total_acquire_time_ms = 0.0
        self._stats_max_acquire_time_ms = 0.0

        # Background tasks
        self._health_check_task: asyncio.Task[None] | None = None
        self._maintenance_task: asyncio.Task[None] | None = None

    @property
    def config(self) -> PoolConfig:
        """Get the pool configuration."""
        return self._config

    @property
    def pool_id(self) -> str:
        """Get the unique pool identifier."""
        return self._pool_id

    @property
    def state(self) -> PoolState:
        """Get the current pool state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Check if the pool is running and accepting requests."""
        return self._state == PoolState.RUNNING

    def _validate_security_context(
        self,
        security_context: SecurityContext,
        required_permission: str | None = None,
    ) -> None:
        """
        Validate security context for operations.

        Args:
            security_context: Security context to validate
            required_permission: Optional specific permission to check

        Raises:
            ValidationError: If security context is missing
            AuthorizationError: If required permission not granted
        """
        if security_context is None:
            raise ValidationError(
                message="Security context is required for pool operations",
                field_name="security_context",
                user_message="Authentication required",
                suggestions=["Provide valid security context"],
            )

        if required_permission and not security_context.has_permission(required_permission):
            raise AuthorizationError(
                message=f"Permission denied: {required_permission}",
                required_permission=required_permission,
                user_id=security_context.user_id,
            )

    def _ensure_running(self) -> None:
        """
        Ensure the pool is running.

        Raises:
            PoolNotInitializedError: If pool not initialized
            PoolClosedError: If pool is closed
        """
        if self._state == PoolState.UNINITIALIZED:
            raise PoolNotInitializedError(pool_id=self._pool_id)
        if self._state in (PoolState.CLOSED, PoolState.DRAINING):
            raise PoolClosedError(pool_id=self._pool_id)

    async def _create_connection(self) -> PooledConnection[ConnectionT]:
        """
        Create a new pooled connection.

        Returns:
            New PooledConnection wrapper

        Raises:
            ConnectionPoolError: If creation fails
        """
        for attempt in range(self._config.retry_attempts):
            try:
                connection = await asyncio.wait_for(
                    self._factory(),
                    timeout=self._config.validation_timeout * 2,
                )

                conn_id = f"conn_{uuid.uuid4().hex[:12]}"
                pooled = PooledConnection(
                    connection_id=conn_id,
                    connection=connection,
                )

                self._stats_connections_created += 1
                return pooled

            except TimeoutError as e:
                if attempt == self._config.retry_attempts - 1:
                    raise ConnectionPoolError(
                        message="Timeout creating connection",
                        cause=e,
                        suggestions=["Check network connectivity", "Verify target service"],
                    )
                await asyncio.sleep(self._config.retry_delay)

            except (OSError, ConnectionError, ValueError, RuntimeError) as e:
                if attempt == self._config.retry_attempts - 1:
                    raise ConnectionPoolError(
                        message=f"Failed to create connection: {e}",
                        cause=e,
                        suggestions=[
                            "Check connection parameters",
                            "Verify target service is available",
                        ],
                    )
                await asyncio.sleep(self._config.retry_delay)

        raise ConnectionPoolError(
            message="Failed to create connection after retries",
            suggestions=["Check connection parameters and service availability"],
        )

    async def _validate_connection(
        self,
        pooled: PooledConnection[ConnectionT],
    ) -> bool:
        """
        Validate a connection is still healthy.

        Args:
            pooled: The pooled connection to validate

        Returns:
            True if connection is healthy
        """
        if self._validator is None:
            return True

        try:
            return await asyncio.wait_for(
                self._validator(pooled.connection),
                timeout=self._config.validation_timeout,
            )
        except (TimeoutError, OSError, ConnectionError, RuntimeError):
            return False

    async def _close_connection(
        self,
        pooled: PooledConnection[ConnectionT],
    ) -> None:
        """
        Close a connection.

        Args:
            pooled: The pooled connection to close
        """
        try:
            if self._closer:
                await asyncio.wait_for(
                    self._closer(pooled.connection),
                    timeout=self._config.validation_timeout,
                )
        except (TimeoutError, OSError, ConnectionError, RuntimeError):
            # Best effort close
            pass
        finally:
            self._stats_connections_closed += 1

    async def _fill_pool(self) -> None:
        """Fill pool to minimum size."""
        current_count = len(self._all_connections)
        needed = self._config.min_size - current_count

        for _ in range(needed):
            try:
                pooled = await self._create_connection()
                self._all_connections[pooled.connection_id] = pooled
                self._idle_connections.append(pooled)
            except (OSError, ConnectionError, RuntimeError, ConnectionPoolError):
                # Log but continue filling
                pass

    async def _evict_stale_connections(self) -> None:
        """Evict idle and expired connections."""
        async with self._lock:
            datetime.now(UTC)
            to_evict: list[PooledConnection[ConnectionT]] = []

            # Check idle connections
            new_idle: deque[PooledConnection[ConnectionT]] = deque()
            while self._idle_connections:
                pooled = self._idle_connections.popleft()

                # Check max lifetime
                if pooled.age_seconds > self._config.max_lifetime:
                    to_evict.append(pooled)
                    continue

                # Check max idle time (but keep min_size connections)
                if (
                    pooled.idle_seconds > self._config.max_idle_time
                    and len(new_idle) >= self._config.min_size
                ):
                    to_evict.append(pooled)
                    continue

                new_idle.append(pooled)

            self._idle_connections = new_idle

            # Close evicted connections
            for pooled in to_evict:
                self._all_connections.pop(pooled.connection_id, None)
                await self._close_connection(pooled)

    async def _run_health_checks(self) -> None:
        """Background task for health checking connections."""
        while self._state == PoolState.RUNNING:
            try:
                await asyncio.sleep(self._config.health_check_interval)

                if self._state != PoolState.RUNNING:
                    break

                async with self._lock:
                    validated: deque[PooledConnection[ConnectionT]] = deque()
                    to_close: list[PooledConnection[ConnectionT]] = []

                    while self._idle_connections:
                        pooled = self._idle_connections.popleft()

                        if await self._validate_connection(pooled):
                            pooled.last_validated_at = datetime.now(UTC)
                            validated.append(pooled)
                        else:
                            self._stats_health_check_failures += 1
                            to_close.append(pooled)

                    self._idle_connections = validated

                    # Close unhealthy connections
                    for pooled in to_close:
                        self._all_connections.pop(pooled.connection_id, None)
                        await self._close_connection(pooled)

                    # Refill pool if needed
                    if len(self._all_connections) < self._config.min_size:
                        await self._fill_pool()

            except asyncio.CancelledError:
                break
            except (OSError, ConnectionError, RuntimeError, ConnectionPoolError):
                # Continue health checking despite errors
                pass

    async def _run_maintenance(self) -> None:
        """Background task for pool maintenance."""
        while self._state == PoolState.RUNNING:
            try:
                await asyncio.sleep(self._config.health_check_interval * 2)

                if self._state != PoolState.RUNNING:
                    break

                await self._evict_stale_connections()

            except asyncio.CancelledError:
                break
            except (OSError, ConnectionError, RuntimeError, ConnectionPoolError):
                # Continue maintenance despite errors
                pass

    async def initialize(self, security_context: SecurityContext) -> None:
        """
        Initialize the connection pool.

        Creates minimum connections and starts background tasks.

        Args:
            security_context: Security context for authorization

        Raises:
            ValidationError: If security context is invalid
            ConnectionPoolError: If initialization fails

        Example:
            ```python
            await pool.initialize(security_context)
            # Pool is now ready for use
            ```
        """
        self._validate_security_context(security_context, self.PERMISSION_POOL_MANAGE)

        async with self._lock:
            if self._state != PoolState.UNINITIALIZED:
                return

            self._state = PoolState.INITIALIZING

            try:
                # Create minimum connections
                await self._fill_pool()

                self._initialized_at = datetime.now(UTC)
                self._state = PoolState.RUNNING

                # Start background tasks
                self._health_check_task = asyncio.create_task(self._run_health_checks())
                self._maintenance_task = asyncio.create_task(self._run_maintenance())

            except (OSError, ConnectionError, RuntimeError, ConnectionPoolError) as e:
                self._state = PoolState.UNINITIALIZED
                raise ConnectionPoolError(
                    message=f"Failed to initialize pool: {e}",
                    cause=e,
                    suggestions=["Check connection parameters", "Verify target service"],
                )

    async def acquire(
        self,
        security_context: SecurityContext,
    ) -> AcquiredConnection[ConnectionT]:
        """
        Acquire a connection from the pool.

        Returns an async context manager that automatically releases
        the connection when done.

        Args:
            security_context: Security context for authorization

        Returns:
            AcquiredConnection context manager

        Raises:
            ValidationError: If security context is invalid
            PoolNotInitializedError: If pool not initialized
            PoolClosedError: If pool is closed
            PoolAcquireTimeoutError: If timeout waiting for connection
            PoolExhaustedError: If pool is exhausted

        Example:
            ```python
            async with pool.acquire(security_context) as conn:
                result = await conn.fetch("SELECT * FROM users")
            # Connection automatically released
            ```
        """
        self._validate_security_context(security_context, self.PERMISSION_POOL_ACQUIRE)
        self._ensure_running()

        start_time = datetime.now(UTC)
        pooled: PooledConnection[ConnectionT] | None = None

        async with self._lock:
            self._pending_count += 1

        try:
            deadline = start_time.timestamp() + self._config.acquire_timeout

            while pooled is None:
                async with self._available:
                    # Check for available connection
                    while self._idle_connections:
                        candidate = self._idle_connections.popleft()

                        # Validate connection
                        if await self._validate_connection(candidate):
                            pooled = candidate
                            break
                        else:
                            # Remove invalid connection
                            self._all_connections.pop(candidate.connection_id, None)
                            self._stats_health_check_failures += 1
                            await self._close_connection(candidate)

                    if pooled is not None:
                        break

                    # Check if we can create a new connection
                    current_count = len(self._all_connections)
                    max_allowed = self._config.max_size
                    if self._config.enable_overflow:
                        max_allowed += self._config.overflow_max_size

                    if current_count < max_allowed:
                        # Create new connection
                        pooled = await self._create_connection()
                        pooled.is_overflow = current_count >= self._config.max_size
                        self._all_connections[pooled.connection_id] = pooled

                        if pooled.is_overflow:
                            self._overflow_connections.add(pooled.connection_id)
                        break

                    # Wait for available connection
                    remaining = deadline - datetime.now(UTC).timestamp()
                    if remaining <= 0:
                        self._stats_timeout_count += 1
                        raise PoolAcquireTimeoutError(
                            timeout_seconds=self._config.acquire_timeout,
                            pool_size=self._config.max_size,
                            active_connections=len(self._active_connections),
                        )

                    try:
                        await asyncio.wait_for(
                            self._available.wait(),
                            timeout=remaining,
                        )
                    except TimeoutError:
                        self._stats_timeout_count += 1
                        raise PoolAcquireTimeoutError(
                            timeout_seconds=self._config.acquire_timeout,
                            pool_size=self._config.max_size,
                            active_connections=len(self._active_connections),
                        )

            # Mark as active
            self._active_connections.add(pooled.connection_id)
            pooled.use_count += 1
            pooled.last_used_at = datetime.now(UTC)

            # Update statistics
            acquire_time_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            self._stats_acquire_count += 1
            self._stats_total_acquire_time_ms += acquire_time_ms
            self._stats_max_acquire_time_ms = max(self._stats_max_acquire_time_ms, acquire_time_ms)

        finally:
            async with self._lock:
                self._pending_count -= 1

        return AcquiredConnection(self, pooled)

    async def release(self, connection: PooledConnection[ConnectionT]) -> None:
        """
        Release a connection back to the pool.

        Called automatically by AcquiredConnection context manager.

        Args:
            connection: The pooled connection to release

        Example:
            ```python
            # Usually called automatically via context manager
            await pool.release(pooled_connection)
            ```
        """
        async with self._available:
            self._active_connections.discard(connection.connection_id)
            self._stats_release_count += 1

            # Close overflow connections instead of returning to pool
            if connection.is_overflow:
                self._overflow_connections.discard(connection.connection_id)
                self._all_connections.pop(connection.connection_id, None)
                await self._close_connection(connection)
            else:
                # Return to idle pool
                connection.last_used_at = datetime.now(UTC)
                self._idle_connections.append(connection)

            # Notify waiters
            self._available.notify()

    async def resize(
        self,
        min_size: int,
        max_size: int,
        security_context: SecurityContext,
    ) -> None:
        """
        Resize the connection pool.

        Adjusts pool size limits and creates/closes connections as needed.

        Args:
            min_size: New minimum pool size
            max_size: New maximum pool size
            security_context: Security context for authorization

        Raises:
            ValidationError: If parameters are invalid
            AuthorizationError: If permission denied

        Example:
            ```python
            await pool.resize(
                min_size=5,
                max_size=20,
                security_context=security_context,
            )
            ```
        """
        self._validate_security_context(security_context, self.PERMISSION_POOL_MANAGE)

        if min_size < 0:
            raise ValidationError(
                message="min_size must be non-negative",
                field_name="min_size",
            )

        if max_size < 1:
            raise ValidationError(
                message="max_size must be at least 1",
                field_name="max_size",
            )

        if min_size > max_size:
            raise ValidationError(
                message="min_size cannot exceed max_size",
                field_name="min_size",
            )

        async with self._lock:
            self._config.min_size = min_size
            self._config.max_size = max_size

            # Ensure minimum connections
            await self._fill_pool()

            # Close excess idle connections
            while len(self._all_connections) > max_size and self._idle_connections:
                pooled = self._idle_connections.pop()
                self._all_connections.pop(pooled.connection_id, None)
                await self._close_connection(pooled)

    async def close_all(self) -> None:
        """
        Close all connections and shut down the pool.

        Drains the pool, waits for active connections to be released,
        and closes all connections.

        Example:
            ```python
            # Graceful shutdown
            await pool.close_all()
            ```
        """
        async with self._lock:
            if self._state == PoolState.CLOSED:
                return

            self._state = PoolState.DRAINING

            # Cancel background tasks
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass

            if self._maintenance_task:
                self._maintenance_task.cancel()
                try:
                    await self._maintenance_task
                except asyncio.CancelledError:
                    pass

            # Close all idle connections
            while self._idle_connections:
                pooled = self._idle_connections.popleft()
                self._all_connections.pop(pooled.connection_id, None)
                await self._close_connection(pooled)

            # Close remaining connections (active will be orphaned)
            for pooled in list(self._all_connections.values()):
                await self._close_connection(pooled)

            self._all_connections.clear()
            self._active_connections.clear()
            self._overflow_connections.clear()
            self._state = PoolState.CLOSED

    async def get_stats(self) -> PoolStats:
        """
        Get current pool statistics.

        Returns comprehensive metrics about pool state and performance.

        Returns:
            PoolStats with current metrics

        Example:
            ```python
            stats = await pool.get_stats()
            print(f"Utilization: {stats.pool_utilization:.1f}%")
            ```
        """
        async with self._lock:
            total = len(self._all_connections)
            active = len(self._active_connections)
            idle = len(self._idle_connections)
            overflow = len(self._overflow_connections)

            uptime = 0.0
            if self._initialized_at:
                uptime = (datetime.now(UTC) - self._initialized_at).total_seconds()

            avg_acquire_time = 0.0
            if self._stats_acquire_count > 0:
                avg_acquire_time = self._stats_total_acquire_time_ms / self._stats_acquire_count

            utilization = 0.0
            if self._config.max_size > 0:
                utilization = (active / self._config.max_size) * 100

            return PoolStats(
                pool_id=self._pool_id,
                state=self._state,
                total_connections=total,
                active_connections=active,
                idle_connections=idle,
                pending_requests=self._pending_count,
                overflow_connections=overflow,
                connections_created=self._stats_connections_created,
                connections_closed=self._stats_connections_closed,
                acquire_count=self._stats_acquire_count,
                release_count=self._stats_release_count,
                timeout_count=self._stats_timeout_count,
                health_check_failures=self._stats_health_check_failures,
                avg_acquire_time_ms=avg_acquire_time,
                max_acquire_time_ms=self._stats_max_acquire_time_ms,
                pool_utilization=utilization,
                uptime_seconds=uptime,
            )


# =============================================================================
# Acquired Connection Context Manager
# =============================================================================


class AcquiredConnection(Generic[ConnectionT]):
    """
    Context manager for acquired connections.

    Ensures connections are properly released back to the pool.

    Example:
        ```python
        async with pool.acquire(security_context) as conn:
            result = await conn.fetch("SELECT * FROM users")
        # Connection automatically released
        ```
    """

    def __init__(
        self,
        pool: ConnectionPool[ConnectionT],
        pooled: PooledConnection[ConnectionT],
    ) -> None:
        """Initialize acquired connection."""
        self._pool = pool
        self._pooled = pooled
        self._released = False

    @property
    def connection(self) -> ConnectionT:
        """Get the underlying connection object."""
        return self._pooled.connection

    @property
    def connection_id(self) -> str:
        """Get the connection ID."""
        return self._pooled.connection_id

    async def __aenter__(self) -> ConnectionT:
        """Return the connection on context entry."""
        return self._pooled.connection

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: Exception | None,
        exc_tb: Any,
    ) -> None:
        """Release the connection on context exit."""
        if not self._released:
            await self._pool.release(self._pooled)
            self._released = True

    async def release(self) -> None:
        """
        Manually release the connection.

        Usually not needed when using context manager.
        """
        if not self._released:
            await self._pool.release(self._pooled)
            self._released = True
