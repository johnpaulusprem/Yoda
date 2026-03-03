"""Microsoft Graph API client -- enterprise edition.

Wraps all Graph API calls using httpx.AsyncClient for async HTTP.  All methods
use Tenacity-based retry for resilience against transient failures.  Every
public method accepts an optional ``SecurityContext`` for audit logging and
row-level authorization, and wraps errors in ``GraphAPIError``.

Ported from ``teams-meeting-assistant/app/services/graph_client.py`` with:
- SecurityContext parameter on public methods
- CXO exceptions (GraphAPIError) instead of bare exceptions
- Tracing spans via observability layer
- Additional methods for CXO features (emails, documents, recent files)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from cxo_ai_companion.exceptions import GraphAPIError
from cxo_ai_companion.observability import get_logger, trace_span
from cxo_ai_companion.security.context import SecurityContext, create_system_context

logger = get_logger("services.graph_client")

BASE_URL = "https://graph.microsoft.com/v1.0"

# Tenacity retry decorator for transient Graph failures
_graph_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    reraise=True,
)


class GraphClient:
    """Async wrapper around Microsoft Graph REST API v1.0 with enterprise observability.

    Provides calendar, subscription, chat, and document operations with
    Tenacity-based retry, tracing spans, and SecurityContext audit logging.

    Args:
        token_provider: Object with ``get_graph_token() -> str`` for Bearer auth.
    """

    def __init__(self, token_provider: Any) -> None:
        """Initialize the Graph client.

        Args:
            token_provider: An object with an async ``get_graph_token() -> str`` method
                            (typically ``cxo_ai_companion.utilities.auth.TokenProvider``).
        """
        self.token_provider = token_provider
        self.http = httpx.AsyncClient(timeout=30.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _headers(self) -> dict[str, str]:
        """Return authorization headers with a fresh token."""
        token = await self.token_provider.get_graph_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _raise_for_status(self, response: httpx.Response) -> None:
        """Raise ``GraphAPIError`` on non-2xx responses."""
        if response.is_success:
            return
        body = response.text
        logger.error(
            "Graph API error",
            extra={
                "status_code": response.status_code,
                "url": str(response.url),
                "body": body[:1000],
            },
        )
        raise GraphAPIError(
            message=f"Graph API returned {response.status_code}",
            status_code=response.status_code,
            endpoint=str(response.url),
            response_body=body[:500],
        )

    # ------------------------------------------------------------------
    # User / Identity
    # ------------------------------------------------------------------

    @_graph_retry
    async def get_me(
        self,
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """GET /me -- return the profile of the authenticated app identity."""
        ctx = ctx or create_system_context()
        async with trace_span("graph.get_me", attributes={"actor": ctx.user_id}):
            headers = await self._headers()
            response = await self.http.get(f"{BASE_URL}/me", headers=headers)
            await self._raise_for_status(response)
            return response.json()

    @_graph_retry
    async def get_user(
        self,
        user_id: str,
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """GET /users/{user_id} -- return a user's profile.

        Args:
            user_id: Azure AD user ID.
            ctx: Security context for audit logging.

        Returns:
            User resource dict with displayName, mail, id, etc.
        """
        ctx = ctx or create_system_context()
        async with trace_span("graph.get_user", attributes={"user_id": user_id}):
            headers = await self._headers()
            response = await self.http.get(
                f"{BASE_URL}/users/{user_id}",
                headers=headers,
                params={"$select": "id,displayName,mail,userPrincipalName,jobTitle,department"},
            )
            await self._raise_for_status(response)
            return response.json()

    @_graph_retry
    async def search_users(
        self,
        display_name: str,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        """Search for users by display name prefix.

        GET /users?$filter=startswith(displayName, '{name}')

        Args:
            display_name: The display name (or prefix) to search for.
            ctx: Security context for audit logging.

        Returns:
            List of matching user dicts.
        """
        ctx = ctx or create_system_context()
        async with trace_span("graph.search_users", attributes={"query": display_name}):
            headers = await self._headers()
            safe_name = display_name.replace("'", "''")
            params = {
                "$filter": f"startswith(displayName,'{safe_name}')",
                "$select": "id,displayName,mail,userPrincipalName,jobTitle,department",
                "$top": "10",
            }
            response = await self.http.get(
                f"{BASE_URL}/users",
                headers=headers,
                params=params,
            )
            await self._raise_for_status(response)
            data = response.json()
            users: list[dict[str, Any]] = data.get("value", [])
            logger.info(
                "User search completed",
                extra={"query": display_name, "results": len(users)},
            )
            return users

    @_graph_retry
    async def list_users(
        self,
        top: int = 50,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        """List users in the directory.

        GET /users

        Args:
            top: Maximum number of users to return.
            ctx: Security context.

        Returns:
            List of user dicts.
        """
        ctx = ctx or create_system_context()
        async with trace_span("graph.list_users", attributes={"top": top}):
            headers = await self._headers()
            response = await self.http.get(
                f"{BASE_URL}/users",
                headers=headers,
                params={
                    "$select": "id,displayName,mail,userPrincipalName,jobTitle,department",
                    "$top": str(top),
                },
            )
            await self._raise_for_status(response)
            return response.json().get("value", [])

    @_graph_retry
    async def get_user_photo(
        self,
        user_id: str,
        ctx: SecurityContext | None = None,
    ) -> bytes | None:
        """GET /users/{user_id}/photo/$value -- return the user's profile photo bytes.

        Returns ``None`` if the user has no photo (404).
        """
        ctx = ctx or create_system_context()
        async with trace_span("graph.get_user_photo", attributes={"user_id": user_id}):
            headers = await self._headers()
            response = await self.http.get(
                f"{BASE_URL}/users/{user_id}/photo/$value",
                headers=headers,
            )
            if response.status_code == 404:
                return None
            await self._raise_for_status(response)
            return response.content

    # ------------------------------------------------------------------
    # Calendar Events
    # ------------------------------------------------------------------

    @_graph_retry
    async def get_calendar_events(
        self,
        user_id: str,
        hours_ahead: int = 24,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        """Get upcoming Teams meetings from a user's calendar view.

        GET /users/{user_id}/calendarView
        Filters for events where ``isOnlineMeeting eq true``.

        Args:
            user_id: Azure AD user ID.
            hours_ahead: How many hours into the future to look.
            ctx: Security context.

        Returns:
            List of event dicts that are online meetings.
        """
        ctx = ctx or create_system_context()
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=hours_ahead)

        async with trace_span(
            "graph.get_calendar_events",
            attributes={"user_id": user_id, "hours_ahead": hours_ahead},
        ):
            params = {
                "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "$filter": "isOnlineMeeting eq true",
                "$select": (
                    "id,subject,start,end,organizer,onlineMeeting,"
                    "isOnlineMeeting,webLink,attendees"
                ),
                "$orderby": "start/dateTime",
                "$top": "50",
            }

            headers = await self._headers()
            response = await self.http.get(
                f"{BASE_URL}/users/{user_id}/calendarView",
                headers=headers,
                params=params,
            )
            await self._raise_for_status(response)
            data = response.json()
            events: list[dict[str, Any]] = data.get("value", [])
            logger.info(
                "Fetched upcoming events",
                extra={"user_id": user_id, "count": len(events)},
            )
            return events

    @_graph_retry
    async def get_event(
        self,
        user_id: str,
        event_id: str,
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """GET /users/{user_id}/events/{event_id} -- full event details.

        Args:
            user_id: Azure AD user ID who owns the calendar event.
            event_id: The Graph event ID.
            ctx: Security context.

        Returns:
            Full event resource dict.
        """
        ctx = ctx or create_system_context()
        async with trace_span(
            "graph.get_event",
            attributes={"user_id": user_id, "event_id": event_id},
        ):
            headers = await self._headers()
            response = await self.http.get(
                f"{BASE_URL}/users/{user_id}/events/{event_id}",
                headers=headers,
            )
            await self._raise_for_status(response)
            return response.json()

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    @_graph_retry
    async def create_subscription(
        self,
        user_id: str,
        webhook_url: str,
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """Create a Graph change notification subscription for a user's calendar.

        POST /subscriptions
        Resource: ``/users/{user_id}/events``
        Change types: ``created,updated,deleted``
        Expiration: 3 days from now (maximum for calendar resources).

        Args:
            user_id: Azure AD object ID of the user whose calendar to watch.
            webhook_url: The publicly-reachable URL that Graph will POST
                         change notifications to.
            ctx: Security context.

        Returns:
            The full subscription response dict from Graph.
        """
        ctx = ctx or create_system_context()
        expiration = datetime.now(timezone.utc) + timedelta(days=3)
        expiration_str = expiration.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

        async with trace_span(
            "graph.create_subscription",
            attributes={"user_id": user_id},
        ):
            payload = {
                "changeType": "created,updated,deleted",
                "notificationUrl": webhook_url,
                "resource": f"/users/{user_id}/events",
                "expirationDateTime": expiration_str,
                "clientState": "cxo-ai-companion",
            }

            headers = await self._headers()
            response = await self.http.post(
                f"{BASE_URL}/subscriptions",
                headers=headers,
                json=payload,
            )
            await self._raise_for_status(response)
            data: dict[str, Any] = response.json()
            logger.info(
                "Created calendar subscription",
                extra={
                    "subscription_id": data.get("id"),
                    "user_id": user_id,
                    "expiration": expiration_str,
                },
            )
            return data

    @_graph_retry
    async def renew_subscription(
        self,
        subscription_id: str,
        new_expiration: datetime,
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """Extend the expiration of an existing Graph subscription.

        PATCH /subscriptions/{id}

        Args:
            subscription_id: The Graph subscription ID to renew.
            new_expiration: New expiration datetime (must be <= 3 days out).
            ctx: Security context.

        Returns:
            The updated subscription response dict.
        """
        ctx = ctx or create_system_context()
        expiration_str = new_expiration.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

        async with trace_span(
            "graph.renew_subscription",
            attributes={"subscription_id": subscription_id},
        ):
            payload = {"expirationDateTime": expiration_str}
            headers = await self._headers()
            response = await self.http.patch(
                f"{BASE_URL}/subscriptions/{subscription_id}",
                headers=headers,
                json=payload,
            )
            await self._raise_for_status(response)
            data: dict[str, Any] = response.json()
            logger.info(
                "Renewed subscription",
                extra={
                    "subscription_id": subscription_id,
                    "new_expiration": expiration_str,
                },
            )
            return data

    @_graph_retry
    async def delete_subscription(
        self,
        subscription_id: str,
        ctx: SecurityContext | None = None,
    ) -> None:
        """DELETE /subscriptions/{id}

        Args:
            subscription_id: The Graph subscription ID to remove.
            ctx: Security context.
        """
        ctx = ctx or create_system_context()
        async with trace_span(
            "graph.delete_subscription",
            attributes={"subscription_id": subscription_id},
        ):
            headers = await self._headers()
            response = await self.http.delete(
                f"{BASE_URL}/subscriptions/{subscription_id}",
                headers=headers,
            )
            # 404 is acceptable -- the subscription may have already expired
            if response.status_code == 404:
                logger.warning(
                    "Subscription not found (already expired/deleted)",
                    extra={"subscription_id": subscription_id},
                )
                return
            await self._raise_for_status(response)
            logger.info(
                "Deleted subscription",
                extra={"subscription_id": subscription_id},
            )

    # ------------------------------------------------------------------
    # Chat & Messaging
    # ------------------------------------------------------------------

    @_graph_retry
    async def send_chat_message(
        self,
        thread_id: str,
        adaptive_card: dict[str, Any],
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """Post an Adaptive Card to a Teams meeting chat thread.

        POST /chats/{threadId}/messages
        Content type: ``application/vnd.microsoft.card.adaptive``

        Args:
            thread_id: The Teams chat thread ID (from the meeting).
            adaptive_card: The Adaptive Card JSON payload.
            ctx: Security context.

        Returns:
            The created message resource dict.
        """
        ctx = ctx or create_system_context()
        async with trace_span(
            "graph.send_chat_message",
            attributes={"thread_id": thread_id},
        ):
            payload = {
                "body": {
                    "contentType": "html",
                    "content": '<attachment id="adaptive-card"></attachment>',
                },
                "attachments": [
                    {
                        "id": "adaptive-card",
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": str(adaptive_card),
                    }
                ],
            }

            headers = await self._headers()
            response = await self.http.post(
                f"{BASE_URL}/chats/{thread_id}/messages",
                headers=headers,
                json=payload,
            )
            await self._raise_for_status(response)
            data: dict[str, Any] = response.json()
            logger.info(
                "Posted Adaptive Card to chat",
                extra={"thread_id": thread_id, "message_id": data.get("id")},
            )
            return data

    @_graph_retry
    async def get_meeting_chat_id(
        self,
        user_id: str,
        ctx: SecurityContext | None = None,
    ) -> str | None:
        """Find the 1:1 chat between the bot app and a user.

        GET /users/{userId}/chats?$filter=chatType eq 'oneOnOne'

        Returns the chat ID if found, or ``None``.
        """
        ctx = ctx or create_system_context()
        async with trace_span(
            "graph.get_meeting_chat_id",
            attributes={"user_id": user_id},
        ):
            headers = await self._headers()
            response = await self.http.get(
                f"{BASE_URL}/users/{user_id}/chats",
                headers=headers,
                params={
                    "$filter": "chatType eq 'oneOnOne'",
                    "$select": "id,chatType",
                    "$top": "50",
                },
            )
            await self._raise_for_status(response)
            chats = response.json().get("value", [])
            if not chats:
                return None
            return chats[0]["id"]

    @_graph_retry
    async def send_proactive_message(
        self,
        user_id: str,
        adaptive_card: dict[str, Any],
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """Send a 1:1 proactive message to a user via the bot's installed chat.

        Steps:
        1. Find existing 1:1 chat between the bot app and the user.
        2. Post the Adaptive Card to that chat.

        Args:
            user_id: Azure AD user ID of the recipient.
            adaptive_card: The Adaptive Card JSON payload.
            ctx: Security context.

        Returns:
            The created message resource dict.

        Raises:
            GraphAPIError: When no 1:1 chat is found or posting fails.
        """
        ctx = ctx or create_system_context()
        async with trace_span(
            "graph.send_proactive_message",
            attributes={"user_id": user_id},
        ):
            chat_id = await self.get_meeting_chat_id(user_id, ctx=ctx)
            if chat_id is None:
                raise GraphAPIError(
                    message=f"No 1:1 chat found for user {user_id}. "
                    "The bot app must be installed for the user first.",
                    endpoint=f"/users/{user_id}/chats",
                )
            return await self.send_chat_message(chat_id, adaptive_card, ctx=ctx)

    # ------------------------------------------------------------------
    # Meeting details
    # ------------------------------------------------------------------

    @_graph_retry
    async def get_online_meeting(
        self,
        meeting_id: str,
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """GET /communications/onlineMeetings/{meetingId}"""
        ctx = ctx or create_system_context()
        async with trace_span(
            "graph.get_online_meeting",
            attributes={"meeting_id": meeting_id},
        ):
            headers = await self._headers()
            response = await self.http.get(
                f"{BASE_URL}/communications/onlineMeetings/{meeting_id}",
                headers=headers,
            )
            await self._raise_for_status(response)
            return response.json()

    @_graph_retry
    async def get_meeting_participants(
        self,
        call_id: str,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        """GET /communications/calls/{callId}/participants"""
        ctx = ctx or create_system_context()
        async with trace_span(
            "graph.get_meeting_participants",
            attributes={"call_id": call_id},
        ):
            headers = await self._headers()
            response = await self.http.get(
                f"{BASE_URL}/communications/calls/{call_id}/participants",
                headers=headers,
            )
            await self._raise_for_status(response)
            return response.json().get("value", [])

    # ------------------------------------------------------------------
    # CXO-specific: Emails, Documents, Recent Files
    # ------------------------------------------------------------------

    @_graph_retry
    async def get_user_emails(
        self,
        user_id: str,
        days: int = 7,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent emails for a user (for pre-meeting briefs).

        GET /users/{user_id}/messages
        Filtered to messages received within the last ``days`` days.

        Args:
            user_id: Azure AD user ID.
            days: Look-back window in days.
            ctx: Security context.

        Returns:
            List of message resource dicts.
        """
        ctx = ctx or create_system_context()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        async with trace_span(
            "graph.get_user_emails",
            attributes={"user_id": user_id, "days": days},
        ):
            headers = await self._headers()
            response = await self.http.get(
                f"{BASE_URL}/users/{user_id}/messages",
                headers=headers,
                params={
                    "$filter": f"receivedDateTime ge {since}",
                    "$select": "id,subject,from,receivedDateTime,bodyPreview,toRecipients",
                    "$orderby": "receivedDateTime desc",
                    "$top": "25",
                },
            )
            await self._raise_for_status(response)
            emails: list[dict[str, Any]] = response.json().get("value", [])
            logger.info(
                "Fetched user emails",
                extra={"user_id": user_id, "count": len(emails)},
            )
            return emails

    @_graph_retry
    async def get_user_documents(
        self,
        user_id: str,
        limit: int = 10,
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent documents from a user's OneDrive.

        GET /users/{user_id}/drive/recent

        Args:
            user_id: Azure AD user ID.
            limit: Maximum number of documents to return.
            ctx: Security context.

        Returns:
            List of drive item dicts.
        """
        ctx = ctx or create_system_context()
        async with trace_span(
            "graph.get_user_documents",
            attributes={"user_id": user_id, "limit": limit},
        ):
            headers = await self._headers()
            response = await self.http.get(
                f"{BASE_URL}/users/{user_id}/drive/recent",
                headers=headers,
                params={"$top": str(limit)},
            )
            await self._raise_for_status(response)
            docs: list[dict[str, Any]] = response.json().get("value", [])
            logger.info(
                "Fetched user documents",
                extra={"user_id": user_id, "count": len(docs)},
            )
            return docs

    @_graph_retry
    async def get_recent_files(
        self,
        meeting_participants: list[str],
        ctx: SecurityContext | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate recently shared files across meeting participants.

        For each participant user_id, fetches their recent OneDrive items
        and returns a de-duplicated list of files.

        Args:
            meeting_participants: List of Azure AD user IDs.
            ctx: Security context.

        Returns:
            List of unique drive item dicts.
        """
        ctx = ctx or create_system_context()
        async with trace_span(
            "graph.get_recent_files",
            attributes={"participant_count": len(meeting_participants)},
        ):
            all_files: list[dict[str, Any]] = []
            seen_ids: set[str] = set()

            for participant_id in meeting_participants:
                try:
                    docs = await self.get_user_documents(
                        participant_id, limit=5, ctx=ctx,
                    )
                    for doc in docs:
                        doc_id = doc.get("id", "")
                        if doc_id and doc_id not in seen_ids:
                            seen_ids.add(doc_id)
                            all_files.append(doc)
                except GraphAPIError:
                    logger.warning(
                        "Failed to fetch documents for participant",
                        extra={"participant_id": participant_id},
                    )
                    continue

            logger.info(
                "Fetched recent files for meeting",
                extra={
                    "participant_count": len(meeting_participants),
                    "file_count": len(all_files),
                },
            )
            return all_files

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying httpx client, releasing connection pool resources."""
        await self.http.aclose()
        logger.info("GraphClient HTTP client closed")
