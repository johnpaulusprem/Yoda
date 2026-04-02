"""
Base data access infrastructure for the YODA Foundation Library.

Provides foundational abstractions for all data connectors:
- BaseConnector: Abstract base class for all data connectors
- ConnectionPool: Generic async connection pool implementation
- Query results: Row, ResultSet, QueryResult
- Credentials: Secure credential storage and management
- Health checks: Standardized health checking
- GenericRepository: Base class for domain repositories
"""

from yoda_foundation.data_access.base.connection_pool import (
    AcquiredConnection,
    ConnectionCloser,
    ConnectionFactory,
    ConnectionPool,
    ConnectionValidator,
    PoolAcquireTimeoutError,
    PoolClosedError,
    PoolConfig,
    PooledConnection,
    PoolExhaustedError,
    PoolNotInitializedError,
    PoolState,
    PoolStats,
)
from yoda_foundation.data_access.base.connector import (
    BaseConnector,
    ConnectionInfo,
    ConnectionState,
    ConnectorConfig,
    ConnectorError,
    ConnectorNotConnectedError,
    ConnectorTimeoutError,
    ConnectorType,
    HealthCheckResult,
)
from yoda_foundation.data_access.base.credentials import (
    CredentialEncryptionError,
    CredentialError,
    CredentialNotFoundError,
    Credentials,
    CredentialStore,
    CredentialType,
    CredentialValidationError,
    EncryptionProvider,
    InMemoryCredentialStore,
    SimpleEncryptionProvider,
)
from yoda_foundation.data_access.base.health_check import (
    CompositeHealthChecker,
    HealthChecker,
    HealthCheckError,
    HealthCheckFn,
    HealthStatus,
    create_ping_check,
)
from yoda_foundation.data_access.base.query_result import (
    QueryResult,
    ResultSet,
    Row,
)
from yoda_foundation.data_access.base.repository import GenericRepository

__all__ = [
    # Connector
    "ConnectorType",
    "ConnectionState",
    "ConnectorConfig",
    "ConnectionInfo",
    "HealthCheckResult",
    "BaseConnector",
    "ConnectorError",
    "ConnectorNotConnectedError",
    "ConnectorTimeoutError",
    # Pool
    "PoolState",
    "PoolConfig",
    "PoolStats",
    "PooledConnection",
    "ConnectionPool",
    "AcquiredConnection",
    "ConnectionFactory",
    "ConnectionValidator",
    "ConnectionCloser",
    "PoolExhaustedError",
    "PoolAcquireTimeoutError",
    "PoolNotInitializedError",
    "PoolClosedError",
    # Query results
    "Row",
    "ResultSet",
    "QueryResult",
    # Credentials
    "CredentialType",
    "Credentials",
    "CredentialStore",
    "InMemoryCredentialStore",
    "EncryptionProvider",
    "SimpleEncryptionProvider",
    "CredentialError",
    "CredentialNotFoundError",
    "CredentialValidationError",
    "CredentialEncryptionError",
    # Health checks
    "HealthStatus",
    "HealthChecker",
    "CompositeHealthChecker",
    "HealthCheckError",
    "HealthCheckFn",
    "create_ping_check",
    # Repository
    "GenericRepository",
]
