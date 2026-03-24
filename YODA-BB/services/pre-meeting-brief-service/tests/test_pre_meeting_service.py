"""Tests for PreMeetingService."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from pre_meeting_brief_service.services.pre_meeting_service import (
    AttendeeContext,
    PreMeetingBrief,
    PreMeetingService,
)


# ---------------------------------------------------------------------------
# generate_brief
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_brief_meeting_not_found(async_session: AsyncSession):
    """Returns a stub brief when the meeting does not exist."""
    service = PreMeetingService(db=async_session)
    fake_id = uuid.uuid4()
    brief = await service.generate_brief(meeting_id=fake_id, user_id="user-001")

    assert brief.meeting_id == fake_id
    assert brief.meeting_subject == "Unknown Meeting"
    assert brief.attendees == []


@pytest.mark.asyncio
async def test_generate_brief_with_participants(
    async_session: AsyncSession,
    sample_meeting_with_participants,
):
    """Returns a brief with attendees when the meeting has participants."""
    meeting = sample_meeting_with_participants
    service = PreMeetingService(db=async_session)
    brief = await service.generate_brief(
        meeting_id=meeting.id, user_id="aad-user-001"
    )

    assert brief.meeting_id == meeting.id
    assert brief.meeting_subject == "Q4 Budget Review"
    assert len(brief.attendees) == 2
    assert brief.attendees[0].display_name in ("Alice Johnson", "Bob Williams")


@pytest.mark.asyncio
async def test_generate_brief_with_graph_client(
    async_session: AsyncSession,
    sample_meeting_with_participants,
    mock_graph_client: AsyncMock,
):
    """Graph client enriches attendee profiles with job title and department."""
    meeting = sample_meeting_with_participants
    service = PreMeetingService(
        db=async_session, graph_client=mock_graph_client
    )
    brief = await service.generate_brief(
        meeting_id=meeting.id, user_id="aad-user-001"
    )

    # Graph was called for both participants
    assert mock_graph_client.get_user.call_count == 2
    # At least one attendee should have the enriched fields
    enriched = [a for a in brief.attendees if a.job_title == "VP Engineering"]
    assert len(enriched) >= 1


@pytest.mark.asyncio
async def test_generate_brief_graph_client_failure(
    async_session: AsyncSession,
    sample_meeting_with_participants,
):
    """Graph client failures are handled gracefully."""
    meeting = sample_meeting_with_participants
    failing_graph = AsyncMock()
    failing_graph.get_user = AsyncMock(side_effect=RuntimeError("Graph unavailable"))
    failing_graph.get_recent_files = AsyncMock(side_effect=RuntimeError("Graph unavailable"))
    failing_graph.get_user_emails = AsyncMock(side_effect=RuntimeError("Graph unavailable"))

    service = PreMeetingService(
        db=async_session, graph_client=failing_graph
    )
    brief = await service.generate_brief(
        meeting_id=meeting.id, user_id="aad-user-001"
    )

    # Should still succeed with fallback data
    assert brief.meeting_subject == "Q4 Budget Review"
    assert len(brief.attendees) == 2
    assert brief.related_documents == []


@pytest.mark.asyncio
async def test_generate_brief_with_ai_questions(
    async_session: AsyncSession,
    sample_meeting_with_participants,
    mock_ai_connector: AsyncMock,
):
    """AI connector generates suggested questions."""
    meeting = sample_meeting_with_participants
    service = PreMeetingService(
        db=async_session, ai_connector=mock_ai_connector
    )
    brief = await service.generate_brief(
        meeting_id=meeting.id, user_id="aad-user-001"
    )

    assert len(brief.suggested_questions) == 2
    assert "Q4 targets" in brief.suggested_questions[0]


@pytest.mark.asyncio
async def test_generate_brief_ai_failure_uses_fallback(
    async_session: AsyncSession,
    sample_meeting_with_participants,
):
    """AI failure falls back to heuristic question generation."""
    meeting = sample_meeting_with_participants
    failing_ai = AsyncMock()
    failing_ai.complete = AsyncMock(side_effect=RuntimeError("AI unavailable"))

    service = PreMeetingService(
        db=async_session, ai_connector=failing_ai
    )
    brief = await service.generate_brief(
        meeting_id=meeting.id, user_id="aad-user-001"
    )

    # Fallback should still produce at least one question
    assert len(brief.suggested_questions) >= 1
    assert "Q4 Budget Review" in brief.suggested_questions[-1]


# ---------------------------------------------------------------------------
# Fallback questions
# ---------------------------------------------------------------------------


def test_fallback_questions_with_overdue():
    """Fallback generates overdue-item question when attendees have overdue items."""
    brief = PreMeetingBrief(
        meeting_id=uuid.uuid4(),
        meeting_subject="Sprint Review",
        scheduled_start=datetime.now(timezone.utc),
        attendees=[
            AttendeeContext(display_name="Alice", overdue_action_items=2),
            AttendeeContext(display_name="Bob", overdue_action_items=0),
        ],
    )
    questions = PreMeetingService._generate_fallback_questions(brief)
    assert any("Alice" in q for q in questions)


def test_fallback_questions_no_overdue():
    """Fallback generates objective question when no overdue items."""
    brief = PreMeetingBrief(
        meeting_id=uuid.uuid4(),
        meeting_subject="Architecture Review",
        scheduled_start=datetime.now(timezone.utc),
        attendees=[
            AttendeeContext(display_name="Alice", overdue_action_items=0),
        ],
    )
    questions = PreMeetingService._generate_fallback_questions(brief)
    assert any("Architecture Review" in q for q in questions)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_brief_cache_hit(
    async_session: AsyncSession,
    sample_meeting_with_participants,
):
    """Returns cached brief on cache hit."""
    meeting = sample_meeting_with_participants

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value={
        "meeting_id": str(meeting.id),
        "meeting_subject": "Cached Brief",
        "scheduled_start": datetime.now(timezone.utc).isoformat(),
    })

    service = PreMeetingService(db=async_session, cache=mock_cache)
    brief = await service.generate_brief(
        meeting_id=meeting.id, user_id="aad-user-001"
    )

    assert brief.meeting_subject == "Cached Brief"
    mock_cache.get.assert_called_once()


@pytest.mark.asyncio
async def test_generate_brief_cache_miss_writes(
    async_session: AsyncSession,
    sample_meeting_with_participants,
):
    """Writes to cache on cache miss."""
    meeting = sample_meeting_with_participants

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()

    service = PreMeetingService(db=async_session, cache=mock_cache)
    brief = await service.generate_brief(
        meeting_id=meeting.id, user_id="aad-user-001"
    )

    assert brief.meeting_subject == "Q4 Budget Review"
    mock_cache.set.assert_called_once()
