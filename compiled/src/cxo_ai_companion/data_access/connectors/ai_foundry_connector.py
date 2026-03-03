"""Azure AI Foundry connector."""
from __future__ import annotations
import asyncio, logging
from typing import Any
from cxo_ai_companion.data_access.base.connector import BaseConnector, ConnectorConfig, ConnectorType, ConnectionState, HealthCheckResult
from cxo_ai_companion.exceptions import AIProcessingError
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

class AIFoundryConnector(BaseConnector[Any]):
    """Connector for Azure AI Foundry (GPT-4o/4o-mini)."""
    def __init__(self, config: ConnectorConfig, endpoint: str, api_key: str) -> None:
        super().__init__(config); self._endpoint = endpoint; self._api_key = api_key

    @property
    def connector_type(self) -> ConnectorType: return ConnectorType.API

    async def connect(self, security_context: Any) -> None:
        from azure.ai.inference import ChatCompletionsClient
        from azure.core.credentials import AzureKeyCredential
        self._state = ConnectionState.CONNECTING
        self._connection = ChatCompletionsClient(endpoint=self._endpoint, credential=AzureKeyCredential(self._api_key))
        self._state = ConnectionState.CONNECTED; self._connected_at = datetime.now(UTC); self._connection_count += 1

    async def disconnect(self) -> None:
        self._connection = None; self._state = ConnectionState.DISCONNECTED

    async def execute(self, operation: str, security_context: Any, **kwargs: Any) -> Any:
        self._ensure_connected(); self._update_activity()
        return await self.complete(**kwargs)

    async def complete(self, model: str, messages: list[Any], temperature: float = 0.1) -> str:
        from azure.ai.inference.models import SystemMessage, UserMessage
        response = await asyncio.to_thread(self._connection.complete, model=model, messages=messages, temperature=temperature)
        return response.choices[0].message.content

    async def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(healthy=self.is_connected, message="Connected" if self.is_connected else "Not connected")
