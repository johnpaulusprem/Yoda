"""Base connector infrastructure — copied from dhurunthur, adapted for CXO."""
from __future__ import annotations
import asyncio, uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, TypeVar
from cxo_ai_companion.exceptions import ValidationError, AuthorizationError, ConnectorError, ConnectorNotConnectedError, ConnectorTimeoutError
from cxo_ai_companion.exceptions.base import ErrorSeverity

class ConnectorType(Enum):
    SQL = "sql"; NOSQL = "nosql"; GRAPH = "graph"; API = "api"; VECTOR = "vector"; MESSAGE_QUEUE = "message_queue"

class ConnectionState(Enum):
    DISCONNECTED = "disconnected"; CONNECTING = "connecting"; CONNECTED = "connected"
    RECONNECTING = "reconnecting"; FAILED = "failed"; CLOSING = "closing"

@dataclass
class ConnectorConfig:
    timeout: float = 30.0; retry_attempts: int = 3; retry_delay: float = 1.0
    retry_backoff_multiplier: float = 2.0; max_retry_delay: float = 60.0
    connect_timeout: float = 10.0; read_timeout: float = 30.0; write_timeout: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class ConnectionInfo:
    connector_id: str; connector_type: ConnectorType
    state: ConnectionState = ConnectionState.DISCONNECTED
    connected_at: datetime | None = None; last_activity_at: datetime | None = None
    connection_count: int = 0; error_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]:
        return {"connector_id": self.connector_id, "connector_type": self.connector_type.value, "state": self.state.value, "connected_at": self.connected_at.isoformat() if self.connected_at else None, "connection_count": self.connection_count, "error_count": self.error_count}

@dataclass
class HealthCheckResult:
    healthy: bool; latency_ms: float = 0.0; message: str = "OK"
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    warnings: list[str] = field(default_factory=list)
    def to_dict(self) -> dict[str, Any]:
        return {"healthy": self.healthy, "latency_ms": self.latency_ms, "message": self.message, "checked_at": self.checked_at.isoformat()}

ConnectionT = TypeVar("ConnectionT")

class BaseConnector(ABC, Generic[ConnectionT]):
    """Abstract base class for all data connectors."""
    def __init__(self, config: ConnectorConfig) -> None:
        self._config = config; self._connector_id = f"conn_{uuid.uuid4().hex[:12]}"
        self._state = ConnectionState.DISCONNECTED; self._connection: ConnectionT | None = None
        self._connected_at: datetime | None = None; self._last_activity_at: datetime | None = None
        self._connection_count = 0; self._error_count = 0; self._lock = asyncio.Lock()

    @property
    def config(self) -> ConnectorConfig: return self._config
    @property
    def connector_id(self) -> str: return self._connector_id
    @property
    @abstractmethod
    def connector_type(self) -> ConnectorType: ...
    @property
    def is_connected(self) -> bool: return self._state == ConnectionState.CONNECTED and self._connection is not None
    @property
    def state(self) -> ConnectionState: return self._state
    @property
    def connection_info(self) -> ConnectionInfo:
        return ConnectionInfo(connector_id=self._connector_id, connector_type=self.connector_type, state=self._state, connected_at=self._connected_at, last_activity_at=self._last_activity_at, connection_count=self._connection_count, error_count=self._error_count)

    def _validate_security_context(self, security_context: Any, required_permission: str | None = None) -> None:
        if security_context is None:
            raise ValidationError(message="Security context is required", field_name="security_context")
        if required_permission and not security_context.has_permission(required_permission):
            raise AuthorizationError(message=f"Permission denied: {required_permission}", required_permission=required_permission, user_id=security_context.user_id)

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise ConnectorNotConnectedError(connector_id=self._connector_id, connector_type=self.connector_type.value)

    def _update_activity(self) -> None: self._last_activity_at = datetime.now(UTC)
    def _record_error(self) -> None: self._error_count += 1

    @abstractmethod
    async def connect(self, security_context: Any) -> None: ...
    @abstractmethod
    async def disconnect(self) -> None: ...
    @abstractmethod
    async def execute(self, operation: str, security_context: Any, **kwargs: Any) -> Any: ...
    @abstractmethod
    async def health_check(self) -> HealthCheckResult: ...

    async def reconnect(self, security_context: Any) -> None:
        async with self._lock:
            self._state = ConnectionState.RECONNECTING
            await self.disconnect(); await self.connect(security_context)

    async def __aenter__(self) -> BaseConnector[ConnectionT]: return self
    async def __aexit__(self, *args: Any) -> None: await self.disconnect()

    class SessionManager:
        def __init__(self, connector: BaseConnector[ConnectionT], security_context: Any) -> None:
            self._connector = connector; self._security_context = security_context
        async def __aenter__(self) -> BaseConnector[ConnectionT]:
            await self._connector.connect(self._security_context); return self._connector
        async def __aexit__(self, *args: Any) -> None: await self._connector.disconnect()

    def session(self, security_context: Any) -> SessionManager:
        return self.SessionManager(self, security_context)
