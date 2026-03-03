"""Microsoft Graph API connector."""
from __future__ import annotations
import logging
from typing import Any
from cxo_ai_companion.data_access.base.connector import BaseConnector, ConnectorConfig, ConnectorType, ConnectionState, HealthCheckResult
from cxo_ai_companion.exceptions import GraphAPIError
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

class GraphConnector(BaseConnector[Any]):
    """Connector for Microsoft Graph API calls."""
    def __init__(self, config: ConnectorConfig, token_provider: Any) -> None:
        super().__init__(config)
        self._token_provider = token_provider
        self._client: Any = None

    @property
    def connector_type(self) -> ConnectorType: return ConnectorType.API

    async def connect(self, security_context: Any) -> None:
        import httpx
        self._state = ConnectionState.CONNECTING
        token = await self._token_provider.get_graph_token()
        self._client = httpx.AsyncClient(base_url="https://graph.microsoft.com/v1.0", headers={"Authorization": f"Bearer {token}"}, timeout=self._config.timeout)
        self._state = ConnectionState.CONNECTED; self._connected_at = datetime.now(UTC); self._connection_count += 1

    async def disconnect(self) -> None:
        if self._client: await self._client.aclose(); self._client = None
        self._state = ConnectionState.DISCONNECTED

    async def execute(self, operation: str, security_context: Any, **kwargs: Any) -> Any:
        self._ensure_connected()
        method = kwargs.pop("method", "GET"); path = kwargs.pop("path", operation)
        body = kwargs.pop("body", None)
        resp = await self._client.request(method, path, json=body)
        self._update_activity()
        if resp.status_code >= 400:
            raise GraphAPIError(message=f"Graph API {method} {path} failed: {resp.status_code}", endpoint=path, status_code=resp.status_code, response_body=resp.text)
        return resp.json() if resp.content else None

    async def health_check(self) -> HealthCheckResult:
        if not self.is_connected: return HealthCheckResult(healthy=False, message="Not connected")
        try:
            start = datetime.now(UTC)
            await self._client.get("/me")
            latency = (datetime.now(UTC) - start).total_seconds() * 1000
            return HealthCheckResult(healthy=True, latency_ms=latency)
        except Exception as e:
            return HealthCheckResult(healthy=False, message=str(e))

    # Domain-specific methods
    async def get_calendar_events(self, user_id: str, start: str, end: str) -> list[dict[str, Any]]:
        resp = await self.execute(f"/users/{user_id}/calendarView?startDateTime={start}&endDateTime={end}", security_context=None)
        return resp.get("value", [])

    async def create_subscription(self, resource: str, change_type: str, notification_url: str, expiration: str) -> dict[str, Any]:
        body = {"changeType": change_type, "notificationUrl": notification_url, "resource": resource, "expirationDateTime": expiration}
        return await self.execute("/subscriptions", security_context=None, method="POST", path="/subscriptions", body=body)

    async def send_chat_message(self, chat_id: str, content: dict[str, Any]) -> dict[str, Any]:
        body = {"body": {"contentType": "html", "content": content}}
        return await self.execute(f"/chats/{chat_id}/messages", security_context=None, method="POST", path=f"/chats/{chat_id}/messages", body=body)

    async def get_user_emails(self, user_id: str, days: int = 7) -> list[dict[str, Any]]:
        resp = await self.execute(f"/users/{user_id}/messages?$top=20&$orderby=receivedDateTime desc", security_context=None)
        return resp.get("value", [])

    async def get_user_documents(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        resp = await self.execute(f"/users/{user_id}/drive/recent?$top={limit}", security_context=None)
        return resp.get("value", [])
