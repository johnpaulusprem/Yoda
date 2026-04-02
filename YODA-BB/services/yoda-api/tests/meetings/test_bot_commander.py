"""Tests for the BotCommander service."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import _TEST_ENV

pytestmark = pytest.mark.asyncio


async def test_join_meeting_sends_correct_payload():
    """join_meeting should POST to /api/meetings/join with API key header."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from meeting_service.services.bot_commander import BotCommander

        settings = Settings()
        commander = BotCommander(settings=settings)

        # Mock the httpx client
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {"callId": "browser-abc123", "status": "joining"}
        mock_response.raise_for_status = MagicMock()

        commander._client = AsyncMock()
        commander._client.post = AsyncMock(return_value=mock_response)

        result = await commander.join_meeting(
            meeting_id="test-meeting-id",
            join_url="https://teams.microsoft.com/l/meetup-join/test",
        )

        assert result == "browser-abc123"

        # Verify the POST was made
        commander._client.post.assert_called_once()
        call_args = commander._client.post.call_args

        # Check URL
        assert "/api/meetings/join" in str(call_args)

        # Check API key header was included
        headers = call_args[1]["headers"]
        assert "X-API-Key" in headers
        assert headers["Content-Type"] == "application/json"


async def test_leave_meeting():
    """leave_meeting should POST to /api/meetings/leave with callId in body."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from meeting_service.services.bot_commander import BotCommander

        settings = Settings()
        commander = BotCommander(settings=settings)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        commander._client = AsyncMock()
        commander._client.post = AsyncMock(return_value=mock_response)

        await commander.leave_meeting("browser-abc123")

        commander._client.post.assert_called_once()
        call_args = commander._client.post.call_args

        # Check URL points to /api/meetings/leave (not path-param style)
        assert "/api/meetings/leave" in str(call_args)

        # Check body contains callId
        body = call_args[1]["json"]
        assert body["callId"] == "browser-abc123"


async def test_get_capacity():
    """get_capacity should GET /api/meetings/capacity."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from meeting_service.services.bot_commander import BotCommander

        settings = Settings()
        commander = BotCommander(settings=settings)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "canAccept": True,
        }

        commander._client = AsyncMock()
        commander._client.get = AsyncMock(return_value=mock_response)

        result = await commander.get_capacity()
        assert result["canAccept"] is True
