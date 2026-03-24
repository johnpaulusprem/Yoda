"""HTTP client that sends commands to the Browser Bot."""

from __future__ import annotations

import logging
import uuid
from types import TracebackType

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from meeting_service.config import Settings

logger = logging.getLogger(__name__)

# Module-level registry for the shared BotCommander instance.
# Set by main.py lifespan, read by calendar_watcher._execute_bot_join.
# Avoids circular import of app.main.
_shared_instance: BotCommander | None = None


def set_shared_bot_commander(instance: BotCommander | None) -> None:
    global _shared_instance
    _shared_instance = instance


def get_shared_bot_commander() -> BotCommander | None:
    return _shared_instance


class BotCommander:
    """Sends join/leave commands to the Browser Bot via REST.

    Supports async context manager for proper resource cleanup:
        async with BotCommander(settings) as bot:
            await bot.join_meeting(...)
    """

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.BROWSER_BOT_BASE_URL.rstrip("/")
        self.api_key = settings.BROWSER_BOT_API_KEY
        self.hmac_key = settings.INTER_SERVICE_HMAC_KEY
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            ),
        )

    async def __aenter__(self) -> BotCommander:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    def _auth_headers(self) -> dict[str, str]:
        """Build authentication headers for the Browser Bot.

        Browser Bot uses X-API-Key header for authentication.
        """
        headers: dict[str, str] = {"X-Correlation-Id": str(uuid.uuid4())}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def join_meeting(self, meeting_id: str, join_url: str) -> str:
        """Tell the Browser Bot to join a meeting. Returns the call ID."""
        path = "/api/meetings/join"
        body_dict = {"meetingId": meeting_id, "joinUrl": join_url}
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"

        response = await self._client.post(
            f"{self.base_url}{path}",
            json=body_dict,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        call_id = data.get("callId", "")
        logger.info(
            "Bot join requested",
            extra={
                "meeting_id": meeting_id,
                "call_id": call_id,
                "status_code": response.status_code,
            },
        )
        return call_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def leave_meeting(self, call_id: str) -> None:
        """Tell the Browser Bot to leave a meeting."""
        path = "/api/meetings/leave"
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"

        response = await self._client.post(
            f"{self.base_url}{path}",
            json={"callId": call_id},
            headers=headers,
        )
        response.raise_for_status()
        logger.info(
            "Bot leave requested",
            extra={"call_id": call_id, "status_code": response.status_code},
        )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, max=4),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        reraise=True,
    )
    async def get_capacity(self) -> dict:
        """Check how many meetings the bot can still accept."""
        path = "/api/meetings/capacity"
        headers = self._auth_headers()
        response = await self._client.get(
            f"{self.base_url}{path}", headers=headers
        )
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        await self._client.aclose()
