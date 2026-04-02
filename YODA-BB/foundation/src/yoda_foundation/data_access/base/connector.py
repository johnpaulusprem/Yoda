"""
Base connector infrastructure for the Agentic AI Component Library.

This module provides the foundational abstract classes and types for all
data connectors in the library, including SQL, NoSQL, Graph, Document,
API, and Filesystem connectors.

Example:
    ```python
    from yoda_foundation.data_access.base import (
        BaseConnector,
        ConnectorConfig,
        ConnectorType,
        ConnectionInfo,
    )
    from yoda_foundation.security import create_security_context

    # Implement a custom connector
    class MyConnector(BaseConnector):
        async def connect(self, security_context: SecurityContext) -> None:
            # Implementation
            ...

        async def disconnect(self) -> None:
            # Implementation
            ...

        async def execute(
            self,
            operation: str,
            security_context: SecurityContext,
            **kwargs,
        ) -> Any:
            # Implementation
            ...

        async def health_check(self) -> HealthCheckResult:
            # Implementation
            ...

    # Use the connector
    config = ConnectorConfig(timeout=30.0, retry_attempts=3)
    connector = MyConnector(config)

    async with connector.session(security_context) as conn:
        result = await conn.execute("query", security_context, data={"key": "value"})
    ```
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
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
    DataAccessError,
)
from yoda_foundation.security.context import SecurityContext


# =============================================================================
# Type Definitions
# =============================================================================


class ConnectorType(Enum):
    """
    Types of data connectors supported by the library.

    Each connector type has specific characteristics and use cases:
    - SQL: Relational databases (PostgreSQL, MySQL, SQL Server)
    - NOSQL: Document and key-value stores (MongoDB, Redis, DynamoDB)
    - GRAPH: Graph databases (Neo4j, Neptune, ArangoDB)
    - DOCUMENT: Document management systems (S3, Azure Blob, GCS)
    - VECTOR: Vector stores for embeddings (Pinecone, Weaviate, Milvus)
    - API: External API integrations (REST, GraphQL)
    - FILESYSTEM: Local and network file systems
    - MESSAGE_QUEUE: Message brokers (Kafka, RabbitMQ, SQS)

    Example:
        ```python
        if connector.connector_type == ConnectorType.SQL:
            # Use SQL-specific features
            await connector.execute_query(sql)
        ```
    """

    SQL = "sql"
    NOSQL = "nosql"
    GRAPH = "graph"
    DOCUMENT = "document"
    VECTOR = "vector"
    API = "api"
    FILESYSTEM = "filesystem"
    MESSAGE_QUEUE = "message_queue"


class ConnectionState(Enum):
    """
    Connection state for connectors.

    States:
    - DISCONNECTED: Not connected
    - CONNECTING: Connection in progress
    - CONNECTED: Successfully connected
    - RECONNECTING: Attempting to reconnect after failure
    - FAILED: Connection failed, not retrying
    - CLOSING: Disconnection in progress

    Example:
        ```python
        if connector.state == ConnectionState.CONNECTED:
            await connector.execute(query)
        ```
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    CLOSING = "closing"


# =============================================================================
# Configuration Classes
# =============================================================================


@dataclass
class ConnectorConfig:
    """
    Base configuration for all data connectors.

    Provides common configuration options shared across all connector types.
    Specific connectors may extend this with additional options.

    Attributes:
        timeout: Default operation timeout in seconds
        retry_attempts: Number of retry attempts for failed operations
        retry_delay: Base delay between retries in seconds
        retry_backoff_multiplier: Multiplier for exponential backoff
        max_retry_delay: Maximum delay between retries in seconds
        connect_timeout: Timeout for initial connection in seconds
        read_timeout: Timeout for read operations in seconds
        write_timeout: Timeout for write operations in seconds
        metadata: Additional connector-specific metadata

    Example:
        ```python
        config = ConnectorConfig(
            timeout=30.0,
            retry_attempts=5,
            retry_delay=1.0,
            retry_backoff_multiplier=2.0,
            metadata={"environment": "production"},
        )
        ```
    """

    timeout: float = 30.0
    retry_attempts: int = 3
    retry_delay: float = 1.0
    retry_backoff_multiplier: float = 2.0
    max_retry_delay: float = 60.0
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    write_timeout: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.timeout <= 0:
            raise ValidationError(
                message="Timeout must be positive",
                field_name="timeout",
                suggestions=["Set timeout to a positive value"],
            )
        if self.retry_attempts < 0:
            raise ValidationError(
                message="Retry attempts must be non-negative",
                field_name="retry_attempts",
                suggestions=["Set retry_attempts to 0 or more"],
            )
        if self.retry_delay < 0:
            raise ValidationError(
                message="Retry delay must be non-negative",
                field_name="retry_delay",
                suggestions=["Set retry_delay to 0 or more"],
            )


@dataclass
class ConnectionInfo:
    """
    Information about the current connection.

    Provides details about the connection state, timing, and metadata
    for monitoring and debugging purposes.

    Attributes:
        connector_id: Unique identifier for this connector instance
        connector_type: Type of connector
        state: Current connection state
        connected_at: When connection was established
        last_activity_at: Last activity timestamp
        connection_count: Number of successful connections
        error_count: Number of connection errors
        metadata: Additional connection metadata

    Example:
        ```python
        info = connector.connection_info
        print(f"Connected at: {info.connected_at}")
        print(f"Errors: {info.error_count}")
        ```
    """

    connector_id: str
    connector_type: ConnectorType
    state: ConnectionState = ConnectionState.DISCONNECTED
    connected_at: datetime | None = None
    last_activity_at: datetime | None = None
    connection_count: int = 0
    error_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "connector_id": self.connector_id,
            "connector_type": self.connector_type.value,
            "state": self.state.value,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_activity_at": (
                self.last_activity_at.isoformat() if self.last_activity_at else None
            ),
            "connection_count": self.connection_count,
            "error_count": self.error_count,
            "metadata": self.metadata,
        }


@dataclass
class HealthCheckResult:
    """
    Result of a health check operation.

    Contains detailed information about the connector's health status
    including latency, available resources, and any warnings.

    Attributes:
        healthy: Whether the connector is healthy
        latency_ms: Response latency in milliseconds
        message: Human-readable status message
        details: Additional health check details
        checked_at: When the check was performed
        warnings: List of non-critical warnings

    Example:
        ```python
        result = await connector.health_check()
        if not result.healthy:
            logger.warning(f"Unhealthy: {result.message}")
        ```
    """

    healthy: bool
    latency_ms: float = 0.0
    message: str = "OK"
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
            "warnings": self.warnings,
        }


# =============================================================================
# Connector-Specific Exceptions
# =============================================================================


class ConnectorError(DataAccessError):
    """
    Base exception for connector-specific errors.

    Extends DataAccessError with connector-specific context.

    Attributes:
        connector_id: The connector instance ID
        connector_type: Type of connector

    Example:
        ```python
        raise ConnectorError(
            message="Connector operation failed",
            connector_id="conn_abc123",
            connector_type=ConnectorType.SQL,
        )
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        connector_id: str | None = None,
        connector_type: ConnectorType | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize connector error.

        Args:
            message: Error description
            connector_id: Unique connector instance ID
            connector_type: Type of connector
            cause: Original exception
            **kwargs: Additional error parameters
        """
        details = kwargs.pop("details", {})
        details["connector_id"] = connector_id
        if connector_type:
            details["connector_type"] = connector_type.value

        super().__init__(
            message=message,
            connector_type=connector_type.value if connector_type else None,
            cause=cause,
            details=details,
            **kwargs,
        )
        self.connector_id = connector_id


class ConnectorNotConnectedError(ConnectorError):
    """
    Raised when operation attempted on disconnected connector.

    Example:
        ```python
        if not connector.is_connected:
            raise ConnectorNotConnectedError(
                connector_id=connector.connector_id,
                connector_type=connector.connector_type,
            )
        ```
    """

    def __init__(
        self,
        message: str = "Connector is not connected",
        *,
        connector_id: str | None = None,
        connector_type: ConnectorType | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize not connected error."""
        super().__init__(
            message=message,
            connector_id=connector_id,
            connector_type=connector_type,
            severity=ErrorSeverity.MEDIUM,
            retryable=True,
            user_message="Service not available. Please try again.",
            suggestions=[
                "Call connect() before performing operations",
                "Use async context manager for automatic connection management",
            ],
            cause=cause,
            **kwargs,
        )


class ConnectorTimeoutError(ConnectorError):
    """
    Raised when connector operation times out.

    Attributes:
        timeout_seconds: The timeout that was exceeded
        operation: The operation that timed out

    Example:
        ```python
        raise ConnectorTimeoutError(
            connector_id=self.connector_id,
            timeout_seconds=30.0,
            operation="query",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Connector operation timed out",
        *,
        connector_id: str | None = None,
        connector_type: ConnectorType | None = None,
        timeout_seconds: float | None = None,
        operation: str | None = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize timeout error."""
        details = kwargs.pop("details", {})
        details["timeout_seconds"] = timeout_seconds
        details["operation"] = operation

        super().__init__(
            message=message,
            connector_id=connector_id,
            connector_type=connector_type,
            severity=ErrorSeverity.MEDIUM,
            retryable=True,
            user_message="Operation timed out. Please try again.",
            suggestions=[
                f"Consider increasing timeout from {timeout_seconds}s"
                if timeout_seconds
                else "Consider increasing timeout",
                "Check network connectivity",
                "Verify target service is responsive",
            ],
            cause=cause,
            details=details,
            **kwargs,
        )
        self.timeout_seconds = timeout_seconds
        self.operation = operation


# =============================================================================
# Abstract Base Connector
# =============================================================================


# Type variable for connection type
ConnectionT = TypeVar("ConnectionT")


class BaseConnector(ABC, Generic[ConnectionT]):
    """
    Abstract base class for all data connectors.

    Provides the common interface and lifecycle management for all connector
    implementations. Subclasses must implement the abstract methods for
    specific data source types.

    Attributes:
        config: Connector configuration
        connector_type: Type of this connector
        connector_id: Unique instance identifier

    Example:
        ```python
        class PostgresConnector(BaseConnector[asyncpg.Pool]):
            @property
            def connector_type(self) -> ConnectorType:
                return ConnectorType.SQL

            async def connect(self, security_context: SecurityContext) -> None:
                # Implementation
                ...

            async def disconnect(self) -> None:
                # Implementation
                ...

            async def execute(
                self,
                operation: str,
                security_context: SecurityContext,
                **kwargs,
            ) -> Any:
                # Implementation
                ...

            async def health_check(self) -> HealthCheckResult:
                # Implementation
                ...

        # Usage
        connector = PostgresConnector(config)
        async with connector.session(security_context) as conn:
            result = await conn.execute("SELECT * FROM users", security_context)
        ```

    Note:
        All concrete implementations must:
        - Implement all abstract methods
        - Validate SecurityContext for all public operations
        - Use library exceptions, never bare exceptions
        - Support async context manager pattern
    """

    def __init__(self, config: ConnectorConfig) -> None:
        """
        Initialize the base connector.

        Args:
            config: Connector configuration

        Example:
            ```python
            config = ConnectorConfig(timeout=30.0, retry_attempts=3)
            connector = MyConnector(config)
            ```
        """
        self._config = config
        self._connector_id = f"conn_{uuid.uuid4().hex[:12]}"
        self._state = ConnectionState.DISCONNECTED
        self._connection: ConnectionT | None = None
        self._connected_at: datetime | None = None
        self._last_activity_at: datetime | None = None
        self._connection_count = 0
        self._error_count = 0
        self._lock = asyncio.Lock()

    @property
    def config(self) -> ConnectorConfig:
        """Get the connector configuration."""
        return self._config

    @property
    def connector_id(self) -> str:
        """Get the unique connector instance ID."""
        return self._connector_id

    @property
    @abstractmethod
    def connector_type(self) -> ConnectorType:
        """
        Get the type of this connector.

        Returns:
            The ConnectorType for this implementation

        Example:
            ```python
            @property
            def connector_type(self) -> ConnectorType:
                return ConnectorType.SQL
            ```
        """
        pass

    @property
    def is_connected(self) -> bool:
        """
        Check if the connector is currently connected.

        Returns:
            True if connected, False otherwise

        Example:
            ```python
            if connector.is_connected:
                result = await connector.execute(query, context)
            ```
        """
        return self._state == ConnectionState.CONNECTED and self._connection is not None

    @property
    def state(self) -> ConnectionState:
        """
        Get the current connection state.

        Returns:
            Current ConnectionState

        Example:
            ```python
            if connector.state == ConnectionState.FAILED:
                await connector.reconnect(context)
            ```
        """
        return self._state

    @property
    def connection_info(self) -> ConnectionInfo:
        """
        Get information about the current connection.

        Returns:
            ConnectionInfo with current state and statistics

        Example:
            ```python
            info = connector.connection_info
            logger.info(f"Connected since: {info.connected_at}")
            ```
        """
        return ConnectionInfo(
            connector_id=self._connector_id,
            connector_type=self.connector_type,
            state=self._state,
            connected_at=self._connected_at,
            last_activity_at=self._last_activity_at,
            connection_count=self._connection_count,
            error_count=self._error_count,
            metadata=self._config.metadata.copy(),
        )

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

        Example:
            ```python
            self._validate_security_context(
                security_context,
                required_permission="data.read",
            )
            ```
        """
        if security_context is None:
            raise ValidationError(
                message="Security context is required for data operations",
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

    def _ensure_connected(self) -> None:
        """
        Ensure the connector is connected.

        Raises:
            ConnectorNotConnectedError: If not connected

        Example:
            ```python
            self._ensure_connected()
            # Proceed with operation
            ```
        """
        if not self.is_connected:
            raise ConnectorNotConnectedError(
                connector_id=self._connector_id,
                connector_type=self.connector_type,
            )

    def _update_activity(self) -> None:
        """Update last activity timestamp."""
        self._last_activity_at = datetime.now(UTC)

    def _record_error(self) -> None:
        """Record an error occurrence."""
        self._error_count += 1

    @abstractmethod
    async def connect(self, security_context: SecurityContext) -> None:
        """
        Establish connection to the data source.

        Must be called before any operations can be performed. Implementations
        should handle connection pooling and reconnection logic.

        Args:
            security_context: Security context for authorization

        Raises:
            DatabaseConnectionError: If connection fails
            ValidationError: If security context is invalid

        Example:
            ```python
            async def connect(self, security_context: SecurityContext) -> None:
                self._validate_security_context(security_context)

                try:
                    self._state = ConnectionState.CONNECTING
                    self._connection = await create_pool(...)
                    self._state = ConnectionState.CONNECTED
                    self._connected_at = datetime.now(timezone.utc)
                    self._connection_count += 1
                except (ConnectionError, TimeoutError, OSError) as e:
                    self._state = ConnectionState.FAILED
                    self._record_error()
                    raise DatabaseConnectionError(
                        message=f"Failed to connect: {e}",
                        cause=e,
                    )
            ```
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Close connection to the data source.

        Releases all resources and resets connection state. Safe to call
        even if not connected.

        Example:
            ```python
            async def disconnect(self) -> None:
                if self._connection is not None:
                    self._state = ConnectionState.CLOSING
                    await self._connection.close()
                    self._connection = None
                self._state = ConnectionState.DISCONNECTED
            ```
        """
        pass

    @abstractmethod
    async def execute(
        self,
        operation: str,
        security_context: SecurityContext,
        **kwargs: Any,
    ) -> Any:
        """
        Execute an operation on the data source.

        The semantics of 'operation' depend on the connector type:
        - SQL: SQL query string
        - NoSQL: Operation name (find, insert, update, delete)
        - Graph: Graph query (Cypher, Gremlin)
        - Document: Document operation (read, write, delete)

        Args:
            operation: The operation to execute
            security_context: Security context for authorization
            **kwargs: Operation-specific parameters

        Returns:
            Operation result (type depends on connector and operation)

        Raises:
            ConnectorNotConnectedError: If not connected
            ConnectorTimeoutError: If operation times out
            DataAccessError: If operation fails
            AuthorizationError: If permission denied

        Example:
            ```python
            async def execute(
                self,
                operation: str,
                security_context: SecurityContext,
                **kwargs: Any,
            ) -> Any:
                self._validate_security_context(security_context, "data.read")
                self._ensure_connected()

                try:
                    result = await asyncio.wait_for(
                        self._do_execute(operation, **kwargs),
                        timeout=self._config.timeout,
                    )
                    self._update_activity()
                    return result
                except asyncio.TimeoutError as e:
                    raise ConnectorTimeoutError(
                        connector_id=self._connector_id,
                        timeout_seconds=self._config.timeout,
                        operation=operation,
                        cause=e,
                    )
            ```
        """
        pass

    @abstractmethod
    async def health_check(self) -> HealthCheckResult:
        """
        Check the health of the connector and its connection.

        Performs a lightweight check to verify connectivity and basic
        functionality. Should complete quickly and not impact normal operations.

        Returns:
            HealthCheckResult with health status and details

        Example:
            ```python
            async def health_check(self) -> HealthCheckResult:
                start = datetime.now(timezone.utc)

                if not self.is_connected:
                    return HealthCheckResult(
                        healthy=False,
                        message="Not connected",
                    )

                try:
                    await self._ping()
                    latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000

                    return HealthCheckResult(
                        healthy=True,
                        latency_ms=latency,
                        message="OK",
                    )
                except (ConnectionError, TimeoutError, OSError) as e:
                    return HealthCheckResult(
                        healthy=False,
                        message=f"Health check failed: {e}",
                    )
            ```
        """
        pass

    async def reconnect(self, security_context: SecurityContext) -> None:
        """
        Reconnect to the data source.

        Disconnects if currently connected, then establishes a new connection.

        Args:
            security_context: Security context for authorization

        Raises:
            DatabaseConnectionError: If reconnection fails

        Example:
            ```python
            if connector.state == ConnectionState.FAILED:
                await connector.reconnect(security_context)
            ```
        """
        async with self._lock:
            self._state = ConnectionState.RECONNECTING
            await self.disconnect()
            await self.connect(security_context)

    async def __aenter__(self) -> BaseConnector[ConnectionT]:
        """
        Async context manager entry.

        Note: Does not automatically connect. Use session() for auto-connect.

        Returns:
            Self

        Example:
            ```python
            async with connector:
                # connector is available but may not be connected
                pass
            ```
        """
        return self

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: Exception | None,
        exc_tb: Any,
    ) -> None:
        """
        Async context manager exit.

        Ensures clean disconnection on exit.

        Args:
            exc_type: Exception type if error occurred
            exc_val: Exception value if error occurred
            exc_tb: Traceback if error occurred
        """
        await self.disconnect()

    class SessionManager:
        """
        Context manager for automatic connection handling.

        Provides automatic connect/disconnect with security context.
        """

        def __init__(
            self,
            connector: BaseConnector[ConnectionT],
            security_context: SecurityContext,
        ) -> None:
            """Initialize session manager."""
            self._connector = connector
            self._security_context = security_context

        async def __aenter__(self) -> BaseConnector[ConnectionT]:
            """Connect and return connector."""
            await self._connector.connect(self._security_context)
            return self._connector

        async def __aexit__(
            self,
            exc_type: type | None,
            exc_val: Exception | None,
            exc_tb: Any,
        ) -> None:
            """Disconnect on exit."""
            await self._connector.disconnect()

    def session(
        self,
        security_context: SecurityContext,
    ) -> SessionManager:
        """
        Create a session context manager with automatic connection.

        Provides automatic connection and disconnection handling with
        proper security context validation.

        Args:
            security_context: Security context for the session

        Returns:
            SessionManager for use with async with

        Example:
            ```python
            async with connector.session(security_context) as conn:
                result = await conn.execute(query, security_context)
            # Automatically disconnected
            ```
        """
        return self.SessionManager(self, security_context)
