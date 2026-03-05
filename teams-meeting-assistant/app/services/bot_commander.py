"""HTTP client that sends commands to the C# Media Bot."""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import logging
import time
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

from app.config import Settings

logger = logging.getLogger(__name__)


class BotCommander:
    """Sends join/leave commands to the C# Media Bot via REST.

    Supports async context manager for proper resource cleanup:
        async with BotCommander(settings) as bot:
            await bot.join_meeting(...)
    """

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.MEDIA_BOT_BASE_URL.rstrip("/")
        self.hmac_key = settings.INTER_SERVICE_HMAC_KEY
        if not self.hmac_key:
            logger.warning(
                "BotCommander initialized without INTER_SERVICE_HMAC_KEY — "
                "requests will be signed with empty key"
            )
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

    def _sign_request(
        self, method: str, path: str, body: bytes
    ) -> dict[str, str]:
        """Generate HMAC-SHA256 signature headers for inter-service auth."""
        timestamp = str(int(time.time()))
        body_hash = hashlib.sha256(body).hexdigest()
        payload = f"{timestamp}{method}{path}{body_hash}"
        sig = hmac_mod.new(
            self.hmac_key.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "X-Request-Timestamp": timestamp,
            "X-Request-Signature": sig,
            "X-Correlation-Id": str(uuid.uuid4()),
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def join_meeting(self, meeting_id: str, join_url: str) -> str:
        """Tell the C# bot to join a meeting. Returns the Graph call ID."""
        path = "/api/meetings/join"
        body = json.dumps(
            {"meetingId": meeting_id, "joinUrl": join_url}
        ).encode()
        headers = self._sign_request("POST", path, body)
        headers["Content-Type"] = "application/json"

        response = await self._client.post(
            f"{self.base_url}{path}",
            content=body,
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
        """Tell the C# bot to leave a meeting."""
        path = f"/api/meetings/{call_id}/leave"
        body = b""
        headers = self._sign_request("POST", path, body)
        response = await self._client.post(
            f"{self.base_url}{path}", headers=headers
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
        headers = self._sign_request("GET", path, b"")
        response = await self._client.get(
            f"{self.base_url}{path}", headers=headers
        )
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        await self._client.aclose()
