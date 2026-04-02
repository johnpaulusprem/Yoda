"""
Connector Registry for the Agentic AI Component Library.

This module provides a centralized registry for managing data access connectors
with support for lazy initialization, lifecycle management, and health checks.

Example:
    ```python
    from yoda_foundation.data_access import (
        ConnectorRegistry,
        S3Config,
        S3Connector,
        AzureBlobConfig,
        AzureBlobConnector,
    )
    from yoda_foundation.security import create_security_context

    # Get singleton registry
    registry = ConnectorRegistry.get_instance()

    # Register connectors
    s3_config = S3Config(
        bucket="my-bucket",
        region="us-east-1",
        access_key="...",
        secret_key="...",
    )
    registry.register("s3_documents", S3Connector, s3_config)

    azure_config = AzureBlobConfig(
        connection_string="DefaultEndpointsProtocol=https;...",
    )
    registry.register("azure_documents", AzureBlobConnector, azure_config)

    # Get connector (lazy initialization)
    context = create_security_context(user_id="user_123", permissions=["*"])
    s3 = await registry.get("s3_documents", context)

    # Health check all connectors
    health = await registry.health_check_all(context)
    for name, status in health.items():
        print(f"{name}: {status.status}")
    ```
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypeVar

from yoda_foundation.exceptions import (
    DatabaseConnectionError,
    ResourceNotFoundError,
    ValidationError,
)
from yoda_foundation.security import SecurityContext


class HealthStatusCode(Enum):
    """Health status codes for connectors."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    NOT_INITIALIZED = "not_initialized"


@dataclass
class HealthStatus:
    """
    Health status of a connector.

    Attributes:
        status: Health status code
        message: Human-readable status message
        latency_ms: Response latency in milliseconds (if available)
        last_checked: Timestamp of last health check
        details: Additional health check details

    Example:
        ```python
        health = await registry.health_check_all(context)
        for name, status in health.items():
            print(f"{name}: {status.status.value}")
            if status.latency_ms:
                print(f"  Latency: {status.latency_ms}ms")
        ```
    """

    status: HealthStatusCode
    message: str
    latency_ms: float | None = None
    last_checked: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorEntry:
    """
    Registry entry for a connector.

    Attributes:
        name: Unique connector name
        connector_class: Connector class type
        config: Configuration object for the connector
        instance: Instantiated connector (None until initialized)
        is_initialized: Whether the connector has been initialized
        created_at: Registration timestamp
        last_accessed: Last access timestamp
        metadata: Additional metadata

    Example:
        ```python
        entry = registry.get_connector_info("s3_documents")
        print(f"Connector: {entry['name']}")
        print(f"Type: {entry['connector_class']}")
        print(f"Initialized: {entry['is_initialized']}")
        ```
    """

    name: str
    connector_class: type[Any]
    config: Any
    instance: Any | None = None
    is_initialized: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# Type variable for connector types
ConnectorT = TypeVar("ConnectorT")


class ConnectorRegistry:
    """
    Centralized registry for data access connectors.

    Implements the Singleton pattern to ensure only one registry exists.
    Provides thread-safe registration, lazy initialization, and health monitoring.

    Features:
    - Singleton pattern for global access
    - Lazy initialization of connectors
    - Thread-safe registration and access
    - Lifecycle management (connect/disconnect)
    - Health monitoring for all registered connectors

    Attributes:
        _connectors: Dictionary of registered connector entries
        _lock: Thread lock for safe concurrent access

    Example:
        ```python
        # Get singleton instance
        registry = ConnectorRegistry.get_instance()

        # Register a connector
        registry.register(
            name="primary_db",
            connector_class=PostgresConnector,
            config=SQLConfig(host="localhost", ...),
        )

        # Get connector (initializes if needed)
        db = await registry.get("primary_db", security_context)

        # Check health
        health = await registry.health_check_all(security_context)

        # Cleanup
        await registry.shutdown_all()
        ```

    Raises:
        ValidationError: If registration parameters are invalid
        ResourceNotFoundError: If connector not found
        DatabaseConnectionError: If connection fails
    """

    _instance: ConnectorRegistry | None = None
    _instance_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> ConnectorRegistry:
        """
        Create or return singleton instance.

        Returns:
            The singleton ConnectorRegistry instance
        """
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        """Initialize the registry (only once for singleton)."""
        if getattr(self, "_initialized", False):
            return

        self._connectors: dict[str, ConnectorEntry] = {}
        self._lock: threading.Lock = threading.Lock()
        self._async_lock: asyncio.Lock | None = None
        self._initialized = True

    @classmethod
    def get_instance(cls) -> ConnectorRegistry:
        """
        Get the singleton registry instance.

        This is the preferred way to access the registry.

        Returns:
            The singleton ConnectorRegistry instance

        Example:
            ```python
            registry = ConnectorRegistry.get_instance()
            registry.register("my_connector", MyConnector, config)
            ```
        """
        return cls()

    @classmethod
    def reset_instance(cls) -> None:
        """
        Reset the singleton instance (primarily for testing).

        Warning: This will clear all registered connectors.
        Only use in test scenarios.

        Example:
            ```python
            # In test teardown
            ConnectorRegistry.reset_instance()
            ```
        """
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance._connectors.clear()
                cls._instance = None

    def _get_async_lock(self) -> asyncio.Lock:
        """Get or create async lock for the current event loop."""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    def register(
        self,
        name: str,
        connector_class: type[ConnectorT],
        config: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Register a connector with the registry.

        The connector is not initialized at registration time - it will be
        lazily initialized when first accessed via get().

        Args:
            name: Unique name for the connector
            connector_class: The connector class (not an instance)
            config: Configuration object for the connector
            metadata: Optional metadata dictionary

        Raises:
            ValidationError: If name is empty or already registered

        Example:
            ```python
            registry.register(
                name="s3_documents",
                connector_class=S3Connector,
                config=S3Config(
                    bucket="my-bucket",
                    region="us-east-1",
                    access_key="...",
                    secret_key="...",
                ),
                metadata={"environment": "production"},
            )
            ```
        """
        if not name or not isinstance(name, str):
            raise ValidationError(
                message="Connector name must be a non-empty string",
                field_name="name",
            )

        if not connector_class:
            raise ValidationError(
                message="Connector class must be provided",
                field_name="connector_class",
            )

        with self._lock:
            if name in self._connectors:
                raise ValidationError(
                    message=f"Connector '{name}' is already registered",
                    field_name="name",
                )

            entry = ConnectorEntry(
                name=name,
                connector_class=connector_class,
                config=config,
                metadata=metadata or {},
            )
            self._connectors[name] = entry

    async def get(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> Any:
        """
        Get a connector by name, initializing if necessary.

        Implements lazy initialization - the connector is only connected
        when first accessed.

        Args:
            name: Name of the registered connector
            security_context: Security context for authorization

        Returns:
            The initialized connector instance

        Raises:
            ResourceNotFoundError: If connector not registered
            ValidationError: If security context is missing
            DatabaseConnectionError: If connection fails

        Example:
            ```python
            context = create_security_context(
                user_id="user_123",
                permissions=["data.read"],
            )
            s3 = await registry.get("s3_documents", context)

            # Connector is now connected and ready to use
            objects = await s3.list_objects(
                prefix="docs/",
                security_context=context,
            )
            ```
        """
        if security_context is None:
            raise ValidationError(
                message="Security context is required",
                field_name="security_context",
            )

        # Check if connector exists
        with self._lock:
            if name not in self._connectors:
                raise ResourceNotFoundError(
                    message=f"Connector '{name}' not found in registry",
                    resource_type="connector",
                    resource_id=name,
                )

            entry = self._connectors[name]

        # Use async lock for initialization
        async with self._get_async_lock():
            # Double-check after acquiring async lock
            if entry.is_initialized and entry.instance is not None:
                entry.last_accessed = datetime.now(UTC)
                return entry.instance

            # Initialize the connector
            try:
                instance = entry.connector_class(entry.config)
                await instance.connect()

                with self._lock:
                    entry.instance = instance
                    entry.is_initialized = True
                    entry.last_accessed = datetime.now(UTC)

                return instance

            except (OSError, ConnectionError, ValueError, RuntimeError) as e:
                raise DatabaseConnectionError(
                    message=f"Failed to initialize connector '{name}': {e!s}",
                    connector_type=entry.connector_class.__name__,
                    cause=e,
                )

    async def unregister(self, name: str) -> bool:
        """
        Unregister and disconnect a connector.

        Args:
            name: Name of the connector to unregister

        Returns:
            True if connector was unregistered

        Raises:
            ResourceNotFoundError: If connector not found

        Example:
            ```python
            # Remove and disconnect connector
            await registry.unregister("old_s3")
            ```
        """
        with self._lock:
            if name not in self._connectors:
                raise ResourceNotFoundError(
                    message=f"Connector '{name}' not found in registry",
                    resource_type="connector",
                    resource_id=name,
                )

            entry = self._connectors[name]

        # Disconnect if initialized
        if entry.is_initialized and entry.instance is not None:
            try:
                await entry.instance.disconnect()
            except (TimeoutError, OSError, ConnectionError, RuntimeError):
                # Log but don't fail on disconnect errors
                pass

        with self._lock:
            del self._connectors[name]

        return True

    def list_connectors(self) -> list[str]:
        """
        List all registered connector names.

        Returns:
            List of connector names

        Example:
            ```python
            names = registry.list_connectors()
            for name in names:
                print(f"Registered: {name}")
            ```
        """
        with self._lock:
            return list(self._connectors.keys())

    def get_connector_info(self, name: str) -> dict[str, Any]:
        """
        Get detailed information about a registered connector.

        Args:
            name: Name of the connector

        Returns:
            Dictionary with connector information

        Raises:
            ResourceNotFoundError: If connector not found

        Example:
            ```python
            info = registry.get_connector_info("s3_documents")
            print(f"Connector: {info['name']}")
            print(f"Class: {info['connector_class']}")
            print(f"Initialized: {info['is_initialized']}")
            print(f"Created: {info['created_at']}")
            ```
        """
        with self._lock:
            if name not in self._connectors:
                raise ResourceNotFoundError(
                    message=f"Connector '{name}' not found in registry",
                    resource_type="connector",
                    resource_id=name,
                )

            entry = self._connectors[name]
            return {
                "name": entry.name,
                "connector_class": entry.connector_class.__name__,
                "config_type": type(entry.config).__name__,
                "is_initialized": entry.is_initialized,
                "created_at": entry.created_at.isoformat(),
                "last_accessed": entry.last_accessed.isoformat() if entry.last_accessed else None,
                "metadata": entry.metadata,
            }

    def get_all_connector_info(self) -> list[dict[str, Any]]:
        """
        Get information about all registered connectors.

        Returns:
            List of connector information dictionaries

        Example:
            ```python
            all_info = registry.get_all_connector_info()
            for info in all_info:
                print(f"{info['name']}: {info['connector_class']}")
            ```
        """
        with self._lock:
            return [
                {
                    "name": entry.name,
                    "connector_class": entry.connector_class.__name__,
                    "config_type": type(entry.config).__name__,
                    "is_initialized": entry.is_initialized,
                    "created_at": entry.created_at.isoformat(),
                    "last_accessed": entry.last_accessed.isoformat()
                    if entry.last_accessed
                    else None,
                    "metadata": entry.metadata,
                }
                for entry in self._connectors.values()
            ]

    async def health_check(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> HealthStatus:
        """
        Perform health check on a specific connector.

        Args:
            name: Name of the connector
            security_context: Security context for authorization

        Returns:
            HealthStatus with check results

        Raises:
            ResourceNotFoundError: If connector not found
            ValidationError: If security context is missing

        Example:
            ```python
            health = await registry.health_check("s3_documents", context)
            if health.status == HealthStatusCode.HEALTHY:
                print(f"Healthy - latency: {health.latency_ms}ms")
            else:
                print(f"Issue: {health.message}")
            ```
        """
        if security_context is None:
            raise ValidationError(
                message="Security context is required",
                field_name="security_context",
            )

        with self._lock:
            if name not in self._connectors:
                raise ResourceNotFoundError(
                    message=f"Connector '{name}' not found in registry",
                    resource_type="connector",
                    resource_id=name,
                )

            entry = self._connectors[name]

        # Check if initialized
        if not entry.is_initialized or entry.instance is None:
            return HealthStatus(
                status=HealthStatusCode.NOT_INITIALIZED,
                message=f"Connector '{name}' has not been initialized",
            )

        # Perform health check
        start_time = datetime.now(UTC)

        try:
            # Check if connector has health_check method
            if hasattr(entry.instance, "health_check"):
                is_healthy = await entry.instance.health_check()
            elif hasattr(entry.instance, "is_connected"):
                is_healthy = entry.instance.is_connected
            else:
                # Default to checking if instance exists
                is_healthy = True

            end_time = datetime.now(UTC)
            latency_ms = (end_time - start_time).total_seconds() * 1000

            if is_healthy:
                return HealthStatus(
                    status=HealthStatusCode.HEALTHY,
                    message=f"Connector '{name}' is healthy",
                    latency_ms=latency_ms,
                )
            else:
                return HealthStatus(
                    status=HealthStatusCode.UNHEALTHY,
                    message=f"Connector '{name}' reported unhealthy",
                    latency_ms=latency_ms,
                )

        except (TimeoutError, OSError, ConnectionError, ValueError, RuntimeError) as e:
            end_time = datetime.now(UTC)
            latency_ms = (end_time - start_time).total_seconds() * 1000

            return HealthStatus(
                status=HealthStatusCode.UNHEALTHY,
                message=f"Health check failed: {e!s}",
                latency_ms=latency_ms,
                details={"error": str(e), "error_type": type(e).__name__},
            )

    async def health_check_all(
        self,
        security_context: SecurityContext,
    ) -> dict[str, HealthStatus]:
        """
        Perform health checks on all registered connectors.

        Only checks initialized connectors. Connectors that have not been
        initialized will show NOT_INITIALIZED status.

        Args:
            security_context: Security context for authorization

        Returns:
            Dictionary mapping connector names to HealthStatus

        Raises:
            ValidationError: If security context is missing

        Example:
            ```python
            health_results = await registry.health_check_all(context)

            healthy = sum(
                1 for h in health_results.values()
                if h.status == HealthStatusCode.HEALTHY
            )
            total = len(health_results)

            print(f"Health: {healthy}/{total} connectors healthy")

            for name, status in health_results.items():
                icon = "OK" if status.status == HealthStatusCode.HEALTHY else "!!"
                print(f"  [{icon}] {name}: {status.message}")
            ```
        """
        if security_context is None:
            raise ValidationError(
                message="Security context is required",
                field_name="security_context",
            )

        # Get list of connector names
        with self._lock:
            names = list(self._connectors.keys())

        # Run health checks concurrently
        tasks = [self.health_check(name, security_context) for name in names]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build result dictionary
        health_results: dict[str, HealthStatus] = {}
        for name, result in zip(names, results):
            if isinstance(result, Exception):
                health_results[name] = HealthStatus(
                    status=HealthStatusCode.UNKNOWN,
                    message=f"Health check error: {result!s}",
                    details={"error": str(result)},
                )
            else:
                health_results[name] = result

        return health_results

    async def initialize_all(
        self,
        security_context: SecurityContext,
    ) -> dict[str, bool]:
        """
        Initialize all registered connectors.

        Useful for warming up connections at application startup.

        Args:
            security_context: Security context for authorization

        Returns:
            Dictionary mapping connector names to initialization success

        Example:
            ```python
            # At application startup
            results = await registry.initialize_all(system_context)

            failures = [name for name, ok in results.items() if not ok]
            if failures:
                logger.warning(f"Failed to initialize: {failures}")
            ```
        """
        if security_context is None:
            raise ValidationError(
                message="Security context is required",
                field_name="security_context",
            )

        with self._lock:
            names = list(self._connectors.keys())

        results: dict[str, bool] = {}

        for name in names:
            try:
                await self.get(name, security_context)
                results[name] = True
            except (OSError, ConnectionError, ValueError, RuntimeError, DatabaseConnectionError):
                results[name] = False

        return results

    async def shutdown(self, name: str) -> bool:
        """
        Shutdown and disconnect a specific connector.

        The connector remains registered but will need to be
        re-initialized on next access.

        Args:
            name: Name of the connector to shutdown

        Returns:
            True if shutdown was successful

        Raises:
            ResourceNotFoundError: If connector not found

        Example:
            ```python
            # Gracefully shutdown a connector
            await registry.shutdown("s3_documents")
            ```
        """
        with self._lock:
            if name not in self._connectors:
                raise ResourceNotFoundError(
                    message=f"Connector '{name}' not found in registry",
                    resource_type="connector",
                    resource_id=name,
                )

            entry = self._connectors[name]

        if entry.is_initialized and entry.instance is not None:
            try:
                await entry.instance.disconnect()
            except (TimeoutError, OSError, ConnectionError, RuntimeError):
                pass  # Log but don't fail

            with self._lock:
                entry.instance = None
                entry.is_initialized = False

        return True

    async def shutdown_all(self) -> dict[str, bool]:
        """
        Shutdown all registered connectors.

        Useful for graceful application shutdown.

        Returns:
            Dictionary mapping connector names to shutdown success

        Example:
            ```python
            # At application shutdown
            await registry.shutdown_all()
            ```
        """
        with self._lock:
            names = list(self._connectors.keys())

        results: dict[str, bool] = {}

        for name in names:
            try:
                await self.shutdown(name)
                results[name] = True
            except (OSError, ConnectionError, RuntimeError, ResourceNotFoundError):
                results[name] = False

        return results

    async def reconnect(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> Any:
        """
        Reconnect a specific connector.

        Disconnects the current connection and establishes a new one.

        Args:
            name: Name of the connector
            security_context: Security context for authorization

        Returns:
            The reconnected connector instance

        Raises:
            ResourceNotFoundError: If connector not found
            DatabaseConnectionError: If reconnection fails

        Example:
            ```python
            # Force reconnect after network issues
            connector = await registry.reconnect("primary_db", context)
            ```
        """
        await self.shutdown(name)
        return await self.get(name, security_context)

    def is_registered(self, name: str) -> bool:
        """
        Check if a connector is registered.

        Args:
            name: Name of the connector

        Returns:
            True if connector is registered

        Example:
            ```python
            if registry.is_registered("s3_documents"):
                s3 = await registry.get("s3_documents", context)
            ```
        """
        with self._lock:
            return name in self._connectors

    def is_initialized(self, name: str) -> bool:
        """
        Check if a connector is initialized.

        Args:
            name: Name of the connector

        Returns:
            True if connector is initialized, False if not registered
            or not initialized

        Example:
            ```python
            if registry.is_initialized("s3_documents"):
                # Already connected, can use immediately
                pass
            ```
        """
        with self._lock:
            if name not in self._connectors:
                return False
            return self._connectors[name].is_initialized

    def __len__(self) -> int:
        """Return the number of registered connectors."""
        with self._lock:
            return len(self._connectors)

    def __contains__(self, name: str) -> bool:
        """Check if a connector name is registered."""
        return self.is_registered(name)
