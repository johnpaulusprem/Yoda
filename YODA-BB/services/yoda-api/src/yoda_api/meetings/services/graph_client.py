"""Microsoft Graph API client.

Wraps all Graph API calls using httpx.AsyncClient for async HTTP.
All methods use Tenacity-based retry via the ``with_retry`` decorator
for resilience against transient failures.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from yoda_foundation.utils.auth.token_provider import TokenProvider
from yoda_foundation.utils.retry import with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://graph.microsoft.com/v1.0"


class GraphClient:
    """Async wrapper around Microsoft Graph REST API v1.0."""

    def __init__(self, token_provider: TokenProvider) -> None:
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
        """Log and raise on non-2xx responses with the Graph error body."""
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
        response.raise_for_status()

    # ------------------------------------------------------------------
    # Calendar Subscriptions
    # ------------------------------------------------------------------

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def create_calendar_subscription(
        self, user_id: str, webhook_url: str
    ) -> dict:
        """Create a Graph change notification subscription for a user's calendar.

        POST /subscriptions
        Resource: ``/users/{user_id}/events``
        Change types: ``created,updated,deleted``
        Expiration: 3 days from now (maximum for calendar resources).

        Args:
            user_id: Azure AD object ID of the user whose calendar to watch.
            webhook_url: The publicly-reachable URL that Graph will POST
                         change notifications to.

        Returns:
            The full subscription response dict from Graph.
        """
        expiration = datetime.now(timezone.utc) + timedelta(days=3)
        # Graph expects ISO-8601 with explicit timezone
        expiration_str = expiration.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

        payload = {
            "changeType": "created,updated",
            "notificationUrl": webhook_url,
            "resource": f"/users/{user_id}/events",
            "expirationDateTime": expiration_str,
            "clientState": "teams-meeting-assistant",
        }

        headers = await self._headers()
        response = await self.http.post(
            f"{BASE_URL}/subscriptions",
            headers=headers,
            json=payload,
        )
        await self._raise_for_status(response)
        data: dict = response.json()
        logger.info(
            "Created calendar subscription",
            extra={
                "subscription_id": data.get("id"),
                "user_id": user_id,
                "expiration": expiration_str,
            },
        )
        return data

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def renew_subscription(
        self, subscription_id: str, new_expiration: datetime
    ) -> dict:
        """Extend the expiration of an existing Graph subscription.

        PATCH /subscriptions/{id}

        Args:
            subscription_id: The Graph subscription ID to renew.
            new_expiration: New expiration datetime (must be <= 3 days out).

        Returns:
            The updated subscription response dict.
        """
        expiration_str = new_expiration.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
        payload = {"expirationDateTime": expiration_str}

        headers = await self._headers()
        response = await self.http.patch(
            f"{BASE_URL}/subscriptions/{subscription_id}",
            headers=headers,
            json=payload,
        )
        await self._raise_for_status(response)
        data: dict = response.json()
        logger.info(
            "Renewed subscription",
            extra={
                "subscription_id": subscription_id,
                "new_expiration": expiration_str,
            },
        )
        return data

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def delete_subscription(self, subscription_id: str) -> None:
        """Delete a Graph subscription.

        DELETE /subscriptions/{id}

        Args:
            subscription_id: The Graph subscription ID to remove.
        """
        headers = await self._headers()
        response = await self.http.delete(
            f"{BASE_URL}/subscriptions/{subscription_id}",
            headers=headers,
        )
        # 404 is acceptable — the subscription may have already expired
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
    # Calendar Events
    # ------------------------------------------------------------------

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def get_event(self, user_id: str, event_id: str) -> dict:
        """Get full event details including joinWebUrl.

        GET /users/{user_id}/events/{event_id}

        Args:
            user_id: Azure AD user ID who owns the calendar event.
            event_id: The Graph event ID.

        Returns:
            Full event resource dict.
        """
        headers = await self._headers()
        response = await self.http.get(
            f"{BASE_URL}/users/{user_id}/events/{event_id}",
            headers=headers,
        )
        await self._raise_for_status(response)
        return response.json()

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def get_upcoming_events(
        self, user_id: str, hours_ahead: int = 24
    ) -> list[dict]:
        """Get upcoming Teams meetings from a user's calendar view.

        GET /users/{user_id}/calendarView
        Filters for events where ``isOnlineMeeting eq true``.

        Args:
            user_id: Azure AD user ID.
            hours_ahead: How many hours into the future to look (default 24).

        Returns:
            List of event dicts that are online meetings.
        """
        now = datetime.now(timezone.utc)
        end = now + timedelta(hours=hours_ahead)

        params = {
            "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "$filter": "isOnlineMeeting eq true",
            "$select": (
                "id,subject,start,end,organizer,onlineMeeting,"
                "isOnlineMeeting,webLink"
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
        events: list[dict] = data.get("value", [])
        logger.info(
            "Fetched upcoming events",
            extra={"user_id": user_id, "count": len(events)},
        )
        return events

    # ------------------------------------------------------------------
    # Meeting Details
    # ------------------------------------------------------------------

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def get_online_meeting(self, meeting_id: str) -> dict:
        """Get online meeting metadata.

        GET /communications/onlineMeetings/{meetingId}

        Args:
            meeting_id: The onlineMeeting ID (not the calendar event ID).

        Returns:
            Online meeting resource dict.
        """
        headers = await self._headers()
        response = await self.http.get(
            f"{BASE_URL}/communications/onlineMeetings/{meeting_id}",
            headers=headers,
        )
        await self._raise_for_status(response)
        return response.json()

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def get_meeting_participants(self, call_id: str) -> list[dict]:
        """List participants of an active call.

        GET /communications/calls/{callId}/participants

        Args:
            call_id: The call ID from ACS/Graph.

        Returns:
            List of participant dicts.
        """
        headers = await self._headers()
        response = await self.http.get(
            f"{BASE_URL}/communications/calls/{call_id}/participants",
            headers=headers,
        )
        await self._raise_for_status(response)
        data = response.json()
        return data.get("value", [])

    # ------------------------------------------------------------------
    # Chat & Messaging
    # ------------------------------------------------------------------

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def post_to_meeting_chat(
        self, thread_id: str, adaptive_card: dict
    ) -> dict:
        """Post an Adaptive Card to a Teams meeting chat thread.

        POST /chats/{threadId}/messages
        Content type: ``application/vnd.microsoft.card.adaptive``

        Args:
            thread_id: The Teams chat thread ID (from the meeting).
            adaptive_card: The Adaptive Card JSON payload.

        Returns:
            The created message resource dict.
        """
        payload = {
            "body": {
                "contentType": "html",
                "content": (
                    '<attachment id="adaptive-card"></attachment>'
                ),
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
        data: dict = response.json()
        logger.info(
            "Posted Adaptive Card to meeting chat",
            extra={"thread_id": thread_id, "message_id": data.get("id")},
        )
        return data

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def send_proactive_message(
        self, user_id: str, adaptive_card: dict
    ) -> dict:
        """Send a 1:1 proactive message to a user via the bot's installed chat.

        This uses the Graph API to install or find the bot app for the user,
        then posts a message to the 1:1 chat between the bot and the user.

        Steps:
        1. Find existing chat between the bot app and the user
           GET /users/{userId}/chats?$filter=chatType eq 'oneOnOne'
        2. If a chat exists, post the Adaptive Card to that chat.
        3. If no chat exists, install the app for the user first, then post.

        For simplicity, we try to find the existing 1:1 chat via the
        ``/users/{userId}/chats`` endpoint and filter. If the bot has a
        Teams app installation, a 1:1 chat already exists.

        Args:
            user_id: Azure AD user ID of the recipient.
            adaptive_card: The Adaptive Card JSON payload.

        Returns:
            The created message resource dict.
        """
        headers = await self._headers()

        # Step 1: Find the bot's 1:1 chat with this user
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
            logger.warning(
                "No 1:1 chat found for proactive message — "
                "ensure the bot app is installed for the user",
                extra={"user_id": user_id},
            )
            raise ValueError(
                f"No 1:1 chat found for user {user_id}. "
                "The bot app must be installed for the user first."
            )

        # Use the first 1:1 chat (the bot's chat with this user)
        chat_id = chats[0]["id"]

        # Step 2: Post the Adaptive Card
        return await self.post_to_meeting_chat(chat_id, adaptive_card)

    # ------------------------------------------------------------------
    # User Resolution
    # ------------------------------------------------------------------

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def search_user(self, display_name: str) -> list[dict]:
        """Search for users by display name prefix.

        GET /users?$filter=startswith(displayName, '{name}')

        Args:
            display_name: The display name (or prefix) to search for.

        Returns:
            List of matching user dicts with id, displayName, mail, etc.
        """
        headers = await self._headers()
        # Escape single quotes in the name for OData filter
        safe_name = display_name.replace("'", "''")
        params = {
            "$filter": f"startswith(displayName,'{safe_name}')",
            "$select": "id,displayName,mail,userPrincipalName",
            "$top": "10",
        }
        response = await self.http.get(
            f"{BASE_URL}/users",
            headers=headers,
            params=params,
        )
        await self._raise_for_status(response)
        data = response.json()
        users: list[dict] = data.get("value", [])
        logger.info(
            "User search completed",
            extra={"query": display_name, "results": len(users)},
        )
        return users

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def get_user(self, user_id: str) -> dict:
        """Get a user's profile.

        GET /users/{user_id}

        Args:
            user_id: Azure AD user ID.

        Returns:
            User resource dict with displayName, mail, id, etc.
        """
        headers = await self._headers()
        response = await self.http.get(
            f"{BASE_URL}/users/{user_id}",
            headers=headers,
            params={"$select": "id,displayName,mail,userPrincipalName"},
        )
        await self._raise_for_status(response)
        return response.json()

    # ------------------------------------------------------------------
    # Direct Reports
    # ------------------------------------------------------------------

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def get_direct_reports(self, user_id: str) -> list[dict]:
        """Get direct reports for a user from Graph API.

        GET /users/{user_id}/directReports

        Args:
            user_id: Azure AD user ID of the manager.

        Returns:
            List of user resource dicts for each direct report,
            containing id, displayName, mail, etc.
        """
        headers = await self._headers()
        response = await self.http.get(
            f"{BASE_URL}/users/{user_id}/directReports",
            headers=headers,
            params={"$select": "id,displayName,mail,userPrincipalName"},
        )
        await self._raise_for_status(response)
        data = response.json()
        reports: list[dict] = data.get("value", [])
        logger.info(
            "Fetched direct reports",
            extra={"user_id": user_id, "count": len(reports)},
        )
        return reports

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying httpx client, releasing connection pool resources."""
        await self.http.aclose()
        logger.info("GraphClient HTTP client closed")
