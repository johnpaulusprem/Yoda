"""Lightweight Microsoft Graph API client for pre-meeting briefs.

Only includes the Graph calls needed by the brief service:
user profiles, recent files, and user emails.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from yoda_foundation.utils.auth.token_provider import TokenProvider
from yoda_foundation.utils.retry import with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://graph.microsoft.com/v1.0"


class GraphClient:
    """Async Graph API client scoped to pre-meeting brief needs."""

    def __init__(self, token_provider: TokenProvider) -> None:
        self.token_provider = token_provider
        self.http = httpx.AsyncClient(timeout=30.0)

    async def _headers(self) -> dict[str, str]:
        token = await self.token_provider.get_graph_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @with_retry(max_attempts=3, base_delay=1.0)
    async def get_user(self, user_id: str) -> dict[str, Any]:
        """Fetch a user profile from Graph."""
        headers = await self._headers()
        resp = await self.http.get(
            f"{BASE_URL}/users/{user_id}",
            headers=headers,
            params={"$select": "displayName,jobTitle,department,mail"},
        )
        resp.raise_for_status()
        return resp.json()

    @with_retry(max_attempts=3, base_delay=1.0)
    async def get_recent_files(
        self, user_ids: list[str], **kwargs: Any
    ) -> list[dict[str, Any]]:
        """Fetch recently modified files for a set of users."""
        headers = await self._headers()
        all_files: list[dict[str, Any]] = []
        for uid in user_ids[:5]:  # Cap to avoid rate-limit
            try:
                resp = await self.http.get(
                    f"{BASE_URL}/users/{uid}/drive/recent",
                    headers=headers,
                )
                if resp.is_success:
                    items = resp.json().get("value", [])
                    all_files.extend(items)
            except Exception:
                logger.debug("Failed to fetch files for user %s", uid)
        return all_files

    @with_retry(max_attempts=3, base_delay=1.0)
    async def get_user_emails(
        self, user_id: str, days: int = 7, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """Fetch recent emails for a user."""
        from datetime import datetime, timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        headers = await self._headers()
        resp = await self.http.get(
            f"{BASE_URL}/users/{user_id}/messages",
            headers=headers,
            params={
                "$filter": f"receivedDateTime ge {since}",
                "$top": "50",
                "$orderby": "receivedDateTime desc",
                "$select": "subject,from,toRecipients,bodyPreview,receivedDateTime",
            },
        )
        resp.raise_for_status()
        return resp.json().get("value", [])

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.http.aclose()
