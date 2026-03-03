"""Azure Communication Services connector."""
from __future__ import annotations
import logging
from typing import Any
from cxo_ai_companion.data_access.base.connector import BaseConnector, ConnectorConfig, ConnectorType, ConnectionState, HealthCheckResult
from cxo_ai_companion.exceptions import ACSError
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

class ACSConnector(BaseConnector[Any]):
    """Connector for ACS Call Automation."""
    def __init__(self, config: ConnectorConfig, connection_string: str, endpoint: str) -> None:
        super().__init__(config)
        self._connection_string = connection_string; self._endpoint = endpoint

    @property
    def connector_type(self) -> ConnectorType: return ConnectorType.API

    async def connect(self, security_context: Any) -> None:
        from azure.communication.callautomation import CallAutomationClient
        self._state = ConnectionState.CONNECTING
        self._connection = CallAutomationClient.from_connection_string(self._connection_string)
        self._state = ConnectionState.CONNECTED; self._connected_at = datetime.now(UTC); self._connection_count += 1

    async def disconnect(self) -> None:
        self._connection = None; self._state = ConnectionState.DISCONNECTED

    async def execute(self, operation: str, security_context: Any, **kwargs: Any) -> Any:
        self._ensure_connected(); self._update_activity()
        ops = {"join": self._join, "leave": self._leave}
        if operation not in ops: raise ACSError(message=f"Unknown ACS operation: {operation}", operation=operation)
        return await ops[operation](**kwargs)

    async def _join(self, join_url: str, callback_url: str) -> str:
        import asyncio
        from azure.communication.callautomation import CallInvite, CommunicationUserIdentifier
        result = await asyncio.to_thread(self._connection.create_call, target_participant=CallInvite(target=CommunicationUserIdentifier("placeholder")), callback_url=callback_url, teams_meeting_join_url=join_url)
        return result.call_connection_id

    async def _leave(self, call_connection_id: str) -> None:
        import asyncio
        call_connection = self._connection.get_call_connection(call_connection_id)
        await asyncio.to_thread(call_connection.hang_up, is_for_everyone=False)

    async def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(healthy=self.is_connected, message="Connected" if self.is_connected else "Not connected")
