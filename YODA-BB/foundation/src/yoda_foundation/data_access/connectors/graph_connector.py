"""Microsoft Graph API connector."""
from __future__ import annotations
import logging
from typing import Any
from yoda_foundation.data_access.base.connector import BaseConnector, ConnectorConfig, ConnectorType, ConnectionState, HealthCheckResult
from yoda_foundation.exceptions import GraphAPIError
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

    async def get_shared_with_me(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch documents shared with the user via OneDrive sharedWithMe endpoint.

        Args:
            user_id: Azure AD user ID.
            limit: Maximum items to return.

        Returns:
            List of Graph drive-item dicts with name, webUrl, remoteItem, etc.
        """
        resp = await self.execute(
            f"/users/{user_id}/drive/sharedWithMe?$top={limit}",
            security_context=None,
        )
        return resp.get("value", [])

    async def get_sharepoint_recent(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch recently modified documents from a user's OneDrive / SharePoint.

        Args:
            user_id: Azure AD user ID.
            limit: Maximum items to return.

        Returns:
            List of drive-item dicts including name, webUrl, lastModifiedBy,
            file.mimeType, size, parentReference.path, lastModifiedDateTime.
        """
        resp = await self.execute(
            f"/users/{user_id}/drive/recent?$top={limit}&$orderby=lastModifiedDateTime desc",
            security_context=None,
        )
        return resp.get("value", [])

    async def get_meeting_attachments(self, user_id: str, meeting_event_id: str) -> list[dict[str, Any]]:
        """Fetch file attachments from a calendar event.

        Args:
            user_id: Azure AD user ID who owns the calendar.
            meeting_event_id: The Graph event ID for the calendar entry.

        Returns:
            List of attachment dicts (only file attachments, filtered client-side).
        """
        resp = await self.execute(
            f"/users/{user_id}/events/{meeting_event_id}/attachments",
            security_context=None,
        )
        attachments = resp.get("value", [])
        # Only return file attachments (not reference or item attachments)
        return [a for a in attachments if a.get("@odata.type", "") == "#microsoft.graph.fileAttachment"]

    async def get_direct_reports(self, user_id: str) -> list[dict[str, Any]]:
        """Get direct reports for a user from Graph API.

        GET /users/{user_id}/directReports

        Args:
            user_id: Azure AD user ID of the manager.

        Returns:
            List of user resource dicts for each direct report.
        """
        resp = await self.execute(
            f"/users/{user_id}/directReports?$select=id,displayName,mail,userPrincipalName",
            security_context=None,
        )
        return resp.get("value", [])

    async def get_drive_item_details(self, user_id: str, item_id: str) -> dict[str, Any]:
        """Fetch detailed information about a single drive item.

        Args:
            user_id: Azure AD user ID.
            item_id: The drive item ID.

        Returns:
            Drive item dict with full metadata including page count if available.
        """
        resp = await self.execute(
            f"/users/{user_id}/drive/items/{item_id}",
            security_context=None,
        )
        return resp
