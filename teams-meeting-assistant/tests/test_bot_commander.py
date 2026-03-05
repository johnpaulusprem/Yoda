"""Tests for the BotCommander service."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from tests.conftest import _TEST_ENV

pytestmark = pytest.mark.asyncio


async def test_join_meeting_sends_correct_payload():
    """join_meeting should POST to /api/meetings/join with HMAC headers."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.bot_commander import BotCommander

        settings = Settings()
        commander = BotCommander(settings=settings)

        # Mock the httpx client
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"callId": "graph-call-123", "status": "joining"}
        mock_response.raise_for_status = MagicMock()

        commander._client = AsyncMock()
        commander._client.post = AsyncMock(return_value=mock_response)

        result = await commander.join_meeting(
            meeting_id="test-meeting-id",
            join_url="https://teams.microsoft.com/l/meetup-join/test",
        )

        assert result == "graph-call-123"

        # Verify the POST was made
        commander._client.post.assert_called_once()
        call_args = commander._client.post.call_args

        # Check URL
        assert "/api/meetings/join" in call_args[0][0]

        # Check HMAC headers were included
        headers = call_args[1]["headers"]
        assert "X-Request-Timestamp" in headers
        assert "X-Request-Signature" in headers
        assert headers["Content-Type"] == "application/json"

        # Check body contains meeting info
        body = json.loads(call_args[1]["content"])
        assert body["meetingId"] == "test-meeting-id"
        assert body["joinUrl"] == "https://teams.microsoft.com/l/meetup-join/test"


async def test_join_meeting_hmac_signature_is_valid():
    """The HMAC signature should be verifiable with the shared key."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.bot_commander import BotCommander

        settings = Settings()
        commander = BotCommander(settings=settings)

        body = json.dumps({"meetingId": "test", "joinUrl": "https://example.com"}).encode()
        headers = commander._sign_request("POST", "/api/meetings/join", body)

        # Verify signature
        timestamp = headers["X-Request-Timestamp"]
        signature = headers["X-Request-Signature"]

        body_hash = hashlib.sha256(body).hexdigest()
        payload = f"{timestamp}POST/api/meetings/join{body_hash}"
        expected = hmac.new(
            settings.INTER_SERVICE_HMAC_KEY.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        assert signature == expected


async def test_leave_meeting():
    """leave_meeting should POST to /api/meetings/{callId}/leave."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.bot_commander import BotCommander

        settings = Settings()
        commander = BotCommander(settings=settings)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        commander._client = AsyncMock()
        commander._client.post = AsyncMock(return_value=mock_response)

        await commander.leave_meeting("graph-call-123")

        commander._client.post.assert_called_once()
        call_url = commander._client.post.call_args[0][0]
        assert "graph-call-123/leave" in call_url


async def test_get_capacity():
    """get_capacity should GET /api/meetings/capacity."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.bot_commander import BotCommander

        settings = Settings()
        commander = BotCommander(settings=settings)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "currentMeetings": 3,
            "maxMeetings": 5,
            "canAccept": True,
        }

        commander._client = AsyncMock()
        commander._client.get = AsyncMock(return_value=mock_response)

        result = await commander.get_capacity()
        assert result["canAccept"] is True
        assert result["currentMeetings"] == 3
