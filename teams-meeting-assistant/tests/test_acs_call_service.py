"""Tests for the ACS Call Service.

Covers:
- join_meeting returns a call connection ID
- CallDisconnected event triggers post-processing
- ParticipantsUpdated event updates the participant roster
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import _TEST_ENV

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_acs_event(event_type: str, call_connection_id: str, **extra_data) -> dict:
    """Build a mock ACS CloudEvent dict."""
    data = {
        "callConnectionId": call_connection_id,
        "serverCallId": "server-call-001",
        "correlationId": "corr-001",
        **extra_data,
    }
    return {
        "id": str(uuid.uuid4()),
        "source": "calling/callConnections/" + call_connection_id,
        "type": f"Microsoft.Communication.{event_type}",
        "subject": "call",
        "time": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "specversion": "1.0",
    }


# ---------------------------------------------------------------------------
# Test: join_meeting returns connection_id
# ---------------------------------------------------------------------------

async def test_join_meeting_returns_connection_id(
    async_session: AsyncSession,
    sample_meeting,
):
    """join_meeting should call _create_call_with_teams_link and return a call_connection_id."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.acs_call_service import ACSCallService

        settings = Settings()

        # Mock the return value of _create_call_with_teams_link
        mock_call_props = MagicMock()
        mock_call_props.call_connection_id = "acs-conn-returned-123"

        # Reset the meeting status to scheduled so join_meeting can proceed
        sample_meeting.status = "scheduled"
        sample_meeting.acs_call_connection_id = None
        sample_meeting.actual_start = None
        await async_session.commit()

        service = ACSCallService(settings=settings, db=async_session)
        service.client = MagicMock()
        service._create_call_with_teams_link = MagicMock(return_value=mock_call_props)

        # Patch asyncio.to_thread to call the function synchronously
        with patch("asyncio.to_thread", new_callable=lambda: _sync_to_thread):
            result = await service.join_meeting(sample_meeting)

        assert result == "acs-conn-returned-123"

        # Verify meeting was updated
        await async_session.refresh(sample_meeting)
        assert sample_meeting.status == "in_progress"
        assert sample_meeting.acs_call_connection_id == "acs-conn-returned-123"
        assert sample_meeting.actual_start is not None


async def test_join_meeting_payload_structure(
    async_session: AsyncSession,
    sample_meeting,
):
    """join_meeting should build correct payload with teamsMeetingLink."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.acs_call_service import ACSCallService

        settings = Settings()

        mock_call_props = MagicMock()
        mock_call_props.call_connection_id = "acs-conn-payload-test"

        sample_meeting.status = "scheduled"
        sample_meeting.acs_call_connection_id = None
        sample_meeting.actual_start = None
        await async_session.commit()

        service = ACSCallService(settings=settings, db=async_session)
        service.client = MagicMock()
        service._create_call_with_teams_link = MagicMock(return_value=mock_call_props)

        with patch("asyncio.to_thread", new_callable=lambda: _sync_to_thread):
            await service.join_meeting(sample_meeting)

        # Verify the payload passed to _create_call_with_teams_link
        call_args = service._create_call_with_teams_link.call_args
        request_body = call_args[0][0]

        assert request_body["teamsMeetingLink"] == sample_meeting.join_url
        assert "callbackUri" in request_body
        assert request_body["callbackUri"].endswith("/callbacks/acs")
        assert "mediaStreamingOptions" in request_body
        assert request_body["mediaStreamingOptions"]["transportType"] == "websocket"
        assert "transcriptionOptions" in request_body
        assert request_body["transcriptionOptions"]["locale"] == "en-US"
        assert request_body["transcriptionOptions"]["startTranscription"] is True


async def _sync_to_thread(fn, *args, **kwargs):
    """Replacement for asyncio.to_thread that calls synchronously."""
    return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# Test: CallDisconnected triggers processing
# ---------------------------------------------------------------------------

async def test_handle_call_disconnected_triggers_processing(
    async_session: AsyncSession,
    sample_meeting,
):
    """CallDisconnected should mark meeting as completed and trigger post-processing."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.acs_call_service import ACSCallService

        settings = Settings()

        # Set up the meeting as in_progress
        sample_meeting.status = "in_progress"
        sample_meeting.acs_call_connection_id = "acs-conn-disconnect-test"
        await async_session.commit()

        service = ACSCallService(settings=settings, db=async_session)
        service.client = MagicMock()

        # Mock post-processing to verify it was triggered
        service._run_post_processing = AsyncMock()

        event = _make_acs_event(
            "CallDisconnected",
            "acs-conn-disconnect-test",
        )

        # Patch asyncio.create_task to run immediately
        async def run_immediately(coro):
            await coro

        with patch("asyncio.create_task", side_effect=run_immediately):
            await service.handle_callback(event)

        # Verify meeting status updated to completed
        await async_session.refresh(sample_meeting)
        assert sample_meeting.status == "completed"
        assert sample_meeting.actual_end is not None

        # Verify post-processing was triggered
        service._run_post_processing.assert_called_once_with(sample_meeting.id)


# ---------------------------------------------------------------------------
# Test: ParticipantsUpdated
# ---------------------------------------------------------------------------

async def test_handle_participants_updated(
    async_session: AsyncSession,
    sample_meeting,
):
    """ParticipantsUpdated should add new participants to the DB."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.models.meeting import MeetingParticipant
        from app.services.acs_call_service import ACSCallService

        settings = Settings()

        sample_meeting.status = "in_progress"
        sample_meeting.acs_call_connection_id = "acs-conn-participants-test"
        sample_meeting.participant_count = 0
        await async_session.commit()

        service = ACSCallService(settings=settings, db=async_session)
        service.client = MagicMock()

        event = _make_acs_event(
            "ParticipantsUpdated",
            "acs-conn-participants-test",
            participants=[
                {
                    "rawId": "8:acs:user-p1",
                    "displayName": "Participant One",
                    "isMuted": False,
                },
                {
                    "rawId": "8:acs:user-p2",
                    "displayName": "Participant Two",
                    "isMuted": True,
                },
            ],
        )

        await service.handle_callback(event)

        # Verify participants were created
        result = await async_session.execute(
            select(MeetingParticipant).where(
                MeetingParticipant.meeting_id == sample_meeting.id
            )
        )
        participants = result.scalars().all()
        assert len(participants) == 2

        names = {p.display_name for p in participants}
        assert "Participant One" in names
        assert "Participant Two" in names

        # Verify participant count was updated
        await async_session.refresh(sample_meeting)
        assert sample_meeting.participant_count == 2
