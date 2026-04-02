"""
Data Access module for the YODA Foundation Library.

Provides:
- base: Base connector, connection pool, credentials, health checks, query results
- connectors: Azure-specific connectors (Graph, ACS, AI Foundry)
- repositories: Domain-specific repository classes
- registry: Connector registry for managing multiple data sources
"""

# Base infrastructure
from yoda_foundation.data_access.base import (
    AcquiredConnection,
    BaseConnector,
    ConnectionInfo,
    ConnectionPool,
    ConnectionState,
    ConnectorConfig,
    ConnectorError,
    ConnectorNotConnectedError,
    ConnectorTimeoutError,
    ConnectorType,
    HealthCheckResult,
    PoolAcquireTimeoutError,
    PoolClosedError,
    PoolConfig,
    PooledConnection,
    PoolExhaustedError,
    PoolNotInitializedError,
    PoolState,
    PoolStats,
    GenericRepository,
)

# Registry
from yoda_foundation.data_access.registry import (
    ConnectorRegistry,
    HealthStatus,
    HealthStatusCode,
)

# YODA connectors
from yoda_foundation.data_access.connectors import (
    GraphConnector as YodaGraphConnector,
    ACSConnector,
    AIFoundryConnector,
)

# YODA domain repositories
from yoda_foundation.data_access.repositories import (
    MeetingRepository,
    TranscriptRepository,
    ActionItemRepository,
    SummaryRepository,
)

__all__ = [
    # Base infrastructure
    "ConnectorType",
    "ConnectionState",
    "ConnectorConfig",
    "ConnectionInfo",
    "HealthCheckResult",
    "BaseConnector",
    "ConnectorError",
    "ConnectorNotConnectedError",
    "ConnectorTimeoutError",
    "PoolState",
    "PoolConfig",
    "PoolStats",
    "PooledConnection",
    "ConnectionPool",
    "AcquiredConnection",
    "PoolExhaustedError",
    "PoolAcquireTimeoutError",
    "PoolNotInitializedError",
    "PoolClosedError",
    "GenericRepository",
    # Registry
    "ConnectorRegistry",
    "HealthStatus",
    "HealthStatusCode",
    # YODA connectors
    "YodaGraphConnector",
    "ACSConnector",
    "AIFoundryConnector",
    # YODA repositories
    "MeetingRepository",
    "TranscriptRepository",
    "ActionItemRepository",
    "SummaryRepository",
]
