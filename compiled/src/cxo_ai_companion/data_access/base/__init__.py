"""Data access base classes."""
from cxo_ai_companion.data_access.base.connector import BaseConnector, ConnectorConfig, ConnectorType, ConnectionState, ConnectionInfo, HealthCheckResult
from cxo_ai_companion.data_access.base.repository import GenericRepository
__all__ = ["BaseConnector", "ConnectorConfig", "ConnectorType", "ConnectionState", "ConnectionInfo", "HealthCheckResult", "GenericRepository"]
