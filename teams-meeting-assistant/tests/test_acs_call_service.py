"""Tests for the ACS Call Service (event handler).

Covers:
- CallDisconnected event triggers post-processing
- ParticipantsUpdated event updates the participant roster

Note: join_meeting / leave_meeting tests are no longer needed here —
call-making is handled by the C# Media Bot via BotCommander (tested
in test_bot_commander.py).
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
# Test: CallDisconnected triggers processing
# ---------------------------------------------------------------------------

async def test_handle_call_disconnected_triggers_processing(
    async_session: AsyncSession,
    sample_meeting,
):
    """CallDisconnected should mark meeting as completed and trigger post-processing."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.services.acs_call_service import ACSCallService

        # Set up the meeting as in_progress
        sample_meeting.status = "in_progress"
        sample_meeting.acs_call_connection_id = "acs-conn-disconnect-test"
        await async_session.commit()

        service = ACSCallService(db=async_session)

        # Mock post-processing to verify it was triggered
        mock_post_processing = AsyncMock()
        mock_post_processing.run = AsyncMock()
        service.post_processing = mock_post_processing

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
        mock_post_processing.run.assert_called_once_with(sample_meeting.id)


# ---------------------------------------------------------------------------
# Test: ParticipantsUpdated
# ---------------------------------------------------------------------------

async def test_handle_participants_updated(
    async_session: AsyncSession,
    sample_meeting,
):
    """ParticipantsUpdated should add new participants to the DB."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.models.meeting import MeetingParticipant
        from app.services.acs_call_service import ACSCallService

        sample_meeting.status = "in_progress"
        sample_meeting.acs_call_connection_id = "acs-conn-participants-test"
        sample_meeting.participant_count = 0
        await async_session.commit()

        service = ACSCallService(db=async_session)

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
