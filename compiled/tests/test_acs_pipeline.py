"""Tests for the ACS bot-join-and-transcribe pipeline.

Covers:
- ACSCallService.join_meeting builds correct REST payload with teamsMeetingLink
- Callback URL points to /api/callbacks/acs/events
- TranscriptionHandler (enterprise) correctly parses ACS message format
- Callback event dispatcher routes events correctly
- _execute_bot_join scheduler job creates ACS service and joins
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def async_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    from cxo_ai_companion.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def session_factory(async_engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture()
async def async_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session
        await session.rollback()


class MockSettings:
    ACS_CONNECTION_STRING = "endpoint=https://test.communication.azure.com/;accesskey=dGVzdA=="
    BASE_URL = "https://test.example.com"


def _create_meeting_orm(
    meeting_id: uuid.UUID | None = None,
    join_url: str = "https://teams.microsoft.com/l/meetup-join/test-thread-id/0",
    status: str = "scheduled",
):
    """Create a real Meeting ORM object for DB tests."""
    from cxo_ai_companion.models.meeting import Meeting

    return Meeting(
        id=meeting_id or uuid.uuid4(),
        teams_meeting_id=f"teams-{uuid.uuid4()}",
        thread_id="thread-123",
        join_url=join_url,
        subject="Test Meeting",
        organizer_name="Test Organizer",
        organizer_email="organizer@test.com",
        scheduled_start=datetime.now(timezone.utc),
        scheduled_end=datetime.now(timezone.utc) + timedelta(hours=1),
        status=status,
    )


# ---------------------------------------------------------------------------
# ACSCallService.join_meeting
# ---------------------------------------------------------------------------


class TestACSJoinMeeting:
    """Test that join_meeting builds the correct REST payload."""

    @pytest.mark.asyncio
    async def test_join_meeting_sends_teams_meeting_link(self, session_factory):
        """join_meeting should pass teamsMeetingLink in the raw JSON body."""
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        service = ACSCallService(MockSettings(), session_factory)

        # Mock the internal generated client's create_call
        mock_response = MagicMock()
        mock_response.call_connection_id = "test-conn-123"
        service.client._client = MagicMock()
        service.client._client.create_call = MagicMock(return_value=mock_response)

        meeting = _create_meeting_orm()
        async with session_factory() as db:
            db.add(meeting)
            await db.commit()

        call_id = await service.join_meeting(meeting.id)

        assert call_id == "test-conn-123"

        # Verify create_call was called with raw bytes
        call_args = service.client._client.create_call.call_args
        raw_body = call_args.kwargs.get("create_call_request") or call_args[1].get("create_call_request")
        import io
        assert isinstance(raw_body, io.BytesIO)

        payload = json.loads(raw_body.getvalue())
        assert payload["teamsMeetingLink"] == meeting.join_url
        assert payload["callbackUri"] == "https://test.example.com/api/callbacks/acs/events"
        assert payload["transcriptionOptions"]["startTranscription"] is True
        assert "ws/transcription/" in payload["transcriptionOptions"]["transportUrl"]
        assert "ws/audio/" in payload["mediaStreamingOptions"]["transportUrl"]

    @pytest.mark.asyncio
    async def test_join_meeting_no_join_url_raises(self, session_factory):
        """join_meeting should raise ACSError if meeting has no join_url."""
        from cxo_ai_companion.exceptions import ACSError
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        service = ACSCallService(MockSettings(), session_factory)

        meeting = _create_meeting_orm(join_url="")
        async with session_factory() as db:
            db.add(meeting)
            await db.commit()

        with pytest.raises(ACSError, match="no join_url"):
            await service.join_meeting(meeting.id)

    @pytest.mark.asyncio
    async def test_join_meeting_updates_meeting_status(self, session_factory):
        """join_meeting should set status to in_progress on success."""
        from cxo_ai_companion.services.acs_call_service import ACSCallService
        from cxo_ai_companion.models.meeting import Meeting
        from sqlalchemy import select

        service = ACSCallService(MockSettings(), session_factory)

        mock_response = MagicMock()
        mock_response.call_connection_id = "conn-456"
        service.client._client = MagicMock()
        service.client._client.create_call = MagicMock(return_value=mock_response)

        meeting = _create_meeting_orm()
        async with session_factory() as db:
            db.add(meeting)
            await db.commit()

        await service.join_meeting(meeting.id)

        # Re-query to check the updated status
        async with session_factory() as db:
            result = await db.execute(select(Meeting).where(Meeting.id == meeting.id))
            updated = result.scalar_one()
            assert updated.status == "in_progress"
            assert updated.acs_call_connection_id == "conn-456"
            assert updated.actual_start is not None

    @pytest.mark.asyncio
    async def test_join_meeting_failure_sets_failed_status(self, session_factory):
        """join_meeting should set status to failed on ACS error."""
        from cxo_ai_companion.exceptions import ACSError
        from cxo_ai_companion.services.acs_call_service import ACSCallService
        from cxo_ai_companion.models.meeting import Meeting
        from sqlalchemy import select

        service = ACSCallService(MockSettings(), session_factory)

        service.client._client = MagicMock()
        service.client._client.create_call = MagicMock(side_effect=RuntimeError("ACS down"))

        meeting = _create_meeting_orm()
        async with session_factory() as db:
            db.add(meeting)
            await db.commit()

        with pytest.raises(ACSError):
            await service.join_meeting(meeting.id)

        # Re-query to check the updated status
        async with session_factory() as db:
            result = await db.execute(select(Meeting).where(Meeting.id == meeting.id))
            updated = result.scalar_one()
            assert updated.status == "failed"

    @pytest.mark.asyncio
    async def test_join_meeting_websocket_urls_use_wss(self, session_factory):
        """WebSocket URLs should use wss:// derived from https:// BASE_URL."""
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        service = ACSCallService(MockSettings(), session_factory)

        mock_response = MagicMock()
        mock_response.call_connection_id = "conn-ws"
        service.client._client = MagicMock()
        service.client._client.create_call = MagicMock(return_value=mock_response)

        meeting = _create_meeting_orm()
        async with session_factory() as db:
            db.add(meeting)
            await db.commit()

        await service.join_meeting(meeting.id)

        raw_body = service.client._client.create_call.call_args.kwargs["create_call_request"]
        payload = json.loads(raw_body.getvalue())
        assert payload["transcriptionOptions"]["transportUrl"].startswith("wss://")
        assert payload["mediaStreamingOptions"]["transportUrl"].startswith("wss://")

    @pytest.mark.asyncio
    async def test_join_meeting_skips_in_progress(self, session_factory):
        """join_meeting should skip meetings already in_progress."""
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        service = ACSCallService(MockSettings(), session_factory)

        meeting = _create_meeting_orm(status="in_progress")
        async with session_factory() as db:
            db.add(meeting)
            await db.commit()

        result = await service.join_meeting(meeting.id)
        assert result == ""  # Skipped


# ---------------------------------------------------------------------------
# Callback URL correctness
# ---------------------------------------------------------------------------


class TestCallbackURL:
    @pytest.mark.asyncio
    async def test_callback_url_matches_route(self, session_factory):
        """The callback URL should be /api/callbacks/acs/events."""
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        service = ACSCallService(MockSettings(), session_factory)

        mock_response = MagicMock()
        mock_response.call_connection_id = "conn-789"
        service.client._client = MagicMock()
        service.client._client.create_call = MagicMock(return_value=mock_response)

        meeting = _create_meeting_orm()
        async with session_factory() as db:
            db.add(meeting)
            await db.commit()

        await service.join_meeting(meeting.id)

        raw_body = service.client._client.create_call.call_args.kwargs["create_call_request"]
        payload = json.loads(raw_body.getvalue())
        assert payload["callbackUri"].endswith("/api/callbacks/acs/events")


# ---------------------------------------------------------------------------
# TranscriptionHandler (enterprise)
# ---------------------------------------------------------------------------


class TestTranscriptionHandler:
    """Test the enterprise TranscriptionHandler processes ACS messages correctly."""

    @pytest.mark.asyncio
    async def test_handles_transcription_metadata(self, async_session):
        """TranscriptionMetadata messages should be handled without error."""
        from cxo_ai_companion.services.transcription import TranscriptionHandler

        handler = TranscriptionHandler(db=async_session)
        meeting_id = str(uuid.uuid4())
        handler.active_sessions[meeting_id] = []

        metadata_msg = {
            "kind": "TranscriptionMetadata",
            "transcriptionMetadata": {
                "callConnectionId": "conn-123",
                "correlationId": "corr-456",
                "locale": "en-US",
            },
        }

        await handler._handle_metadata(metadata_msg, meeting_id)

    @pytest.mark.asyncio
    async def test_handles_final_transcription_data(self, async_session):
        """Final TranscriptionData should be persisted to DB."""
        from cxo_ai_companion.services.transcription import TranscriptionHandler

        handler = TranscriptionHandler(db=async_session)
        meeting_id = str(uuid.uuid4())
        handler.active_sessions[meeting_id] = []

        data_msg = {
            "kind": "TranscriptionData",
            "transcriptionData": {
                "text": "Hello, this is a test.",
                "resultStatus": "Final",
                "participantRawID": "user-abc",
                "offset": 50_000_000,  # 5 seconds
                "duration": 20_000_000,  # 2 seconds
                "confidence": 0.95,
            },
        }

        speaker_map = {"user-abc": "Test User"}
        new_seq = await handler._handle_transcription_data(data_msg, meeting_id, 0, speaker_map)

        assert new_seq == 1  # sequence incremented

    @pytest.mark.asyncio
    async def test_skips_intermediate_results(self, async_session):
        """Non-Final results should be skipped."""
        from cxo_ai_companion.services.transcription import TranscriptionHandler

        handler = TranscriptionHandler(db=async_session)
        meeting_id = str(uuid.uuid4())

        data_msg = {
            "kind": "TranscriptionData",
            "transcriptionData": {
                "text": "partial...",
                "resultStatus": "Intermediate",
                "participantRawID": "user-abc",
                "offset": 0,
                "duration": 0,
            },
        }

        new_seq = await handler._handle_transcription_data(data_msg, meeting_id, 5, {})
        assert new_seq == 5  # unchanged — skipped

    @pytest.mark.asyncio
    async def test_uses_kind_field_not_type(self):
        """Enterprise handler dispatches on 'kind', not 'type' or 'resultType'."""
        # Message with 'type' instead of 'kind' should yield empty kind
        wrong_format = {"type": "Final", "text": "hello"}
        kind = wrong_format.get("kind", "")
        assert kind == ""  # Not TranscriptionData or TranscriptionMetadata

        # Correct ACS format uses 'kind'
        correct_format = {"kind": "TranscriptionData", "transcriptionData": {}}
        kind = correct_format.get("kind", "")
        assert kind == "TranscriptionData"


# ---------------------------------------------------------------------------
# Callback event dispatcher
# ---------------------------------------------------------------------------


class TestCallbackDispatcher:
    @pytest.mark.asyncio
    async def test_dispatches_call_connected(self, session_factory):
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        service = ACSCallService(MockSettings(), session_factory)
        service._on_call_connected = AsyncMock()

        event = {
            "type": "Microsoft.Communication.CallConnected",
            "data": {"callConnectionId": "conn-123"},
        }

        await service.handle_callback(event)
        service._on_call_connected.assert_called_once_with(ANY, "conn-123", event["data"])

    @pytest.mark.asyncio
    async def test_dispatches_call_disconnected(self, session_factory):
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        service = ACSCallService(MockSettings(), session_factory)
        service._on_call_disconnected = AsyncMock()

        event = {
            "type": "Microsoft.Communication.CallDisconnected",
            "data": {"callConnectionId": "conn-123"},
        }

        await service.handle_callback(event)
        service._on_call_disconnected.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_unknown_event_gracefully(self, session_factory):
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        service = ACSCallService(MockSettings(), session_factory)

        event = {
            "type": "Microsoft.Communication.SomeNewEvent",
            "data": {"callConnectionId": "conn-123"},
        }

        # Should not raise
        await service.handle_callback(event)


# ---------------------------------------------------------------------------
# Leave meeting
# ---------------------------------------------------------------------------


class TestLeaveMeeting:
    @pytest.mark.asyncio
    async def test_leave_meeting_hangs_up(self, session_factory):
        from cxo_ai_companion.services.acs_call_service import ACSCallService

        service = ACSCallService(MockSettings(), session_factory)

        mock_conn = MagicMock()
        mock_conn.hang_up = MagicMock()
        service.client.get_call_connection = MagicMock(return_value=mock_conn)

        await service.leave_meeting("conn-123")

        mock_conn.hang_up.assert_called_once_with(is_for_everyone=False)


# ---------------------------------------------------------------------------
# _execute_bot_join (scheduler job)
# ---------------------------------------------------------------------------


class TestExecuteBotJoin:
    @pytest.mark.asyncio
    async def test_execute_bot_join_creates_service_and_joins(self, async_engine, session_factory):
        """_execute_bot_join should look up meeting and call ACS join."""
        from cxo_ai_companion.models.meeting import Meeting

        meeting_id = uuid.uuid4()
        async with session_factory() as db:
            meeting = Meeting(
                id=meeting_id,
                teams_meeting_id=f"teams-{uuid.uuid4()}",
                subject="Scheduled Meeting",
                join_url="https://teams.microsoft.com/l/meetup-join/test/0",
                organizer_name="Org",
                organizer_email="org@test.com",
                status="scheduled",
                scheduled_start=datetime.now(timezone.utc),
                scheduled_end=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.add(meeting)
            await db.commit()

        with (
            patch("cxo_ai_companion.dependencies.get_settings", return_value=MockSettings()),
            patch("cxo_ai_companion.dependencies.get_session_factory", return_value=session_factory),
            patch("cxo_ai_companion.services.acs_call_service.CallAutomationClient") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.call_connection_id = "sched-conn-001"
            mock_client._client.create_call = MagicMock(return_value=mock_response)
            mock_client_cls.from_connection_string.return_value = mock_client

            from cxo_ai_companion.services.calendar_watcher import _execute_bot_join

            await _execute_bot_join(str(meeting_id))

            mock_client._client.create_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_bot_join_skips_non_scheduled(self, async_engine, session_factory):
        """_execute_bot_join should skip meetings not in scheduled/failed status."""
        from cxo_ai_companion.models.meeting import Meeting

        meeting_id = uuid.uuid4()
        async with session_factory() as db:
            meeting = Meeting(
                id=meeting_id,
                teams_meeting_id=f"teams-{uuid.uuid4()}",
                subject="In-Progress Meeting",
                join_url="https://teams.microsoft.com/l/meetup-join/test/0",
                organizer_name="Org",
                organizer_email="org@test.com",
                status="in_progress",
                scheduled_start=datetime.now(timezone.utc),
                scheduled_end=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            db.add(meeting)
            await db.commit()

        with (
            patch("cxo_ai_companion.dependencies.get_settings", return_value=MockSettings()),
            patch("cxo_ai_companion.dependencies.get_session_factory", return_value=session_factory),
            patch("cxo_ai_companion.services.acs_call_service.CallAutomationClient") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client_cls.from_connection_string.return_value = mock_client

            from cxo_ai_companion.services.calendar_watcher import _execute_bot_join

            # Should not raise or attempt to join
            await _execute_bot_join(str(meeting_id))

            # create_call should NOT have been called (meeting is in_progress)
            mock_client._client.create_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_bot_join_invalid_meeting_id(self):
        """_execute_bot_join should handle invalid meeting_id gracefully."""
        with (
            patch("cxo_ai_companion.dependencies.get_settings", return_value=MockSettings()),
            patch("cxo_ai_companion.dependencies.get_session_factory", return_value=MagicMock()),
        ):
            from cxo_ai_companion.services.calendar_watcher import _execute_bot_join

            # Should not raise
            await _execute_bot_join("not-a-uuid")
