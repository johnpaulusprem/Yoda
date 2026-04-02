"""Tests for insight service analytics."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dashboard_service.services.insight_service import InsightService


@pytest_asyncio.fixture
async def insight_engine():
    """Create a dedicated in-memory SQLite engine for insight tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from yoda_foundation.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def insight_session_factory(insight_engine):
    """Session factory for InsightService."""
    return async_sessionmaker(insight_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def seeded_insight_session_factory(insight_session_factory):
    """Seed test data and return the session factory."""
    from yoda_foundation.models.meeting import Meeting
    from yoda_foundation.models.action_item import ActionItem

    now = datetime.now(timezone.utc)
    async with insight_session_factory() as session:
        meeting = Meeting(
            id=uuid.uuid4(),
            teams_meeting_id="insight-test-001",
            join_url="https://teams.microsoft.com/l/meetup-join/insight-test",
            subject="Insight Test Meeting",
            organizer_id="test-user-001",
            organizer_name="Alice",
            organizer_email="alice@contoso.com",
            scheduled_start=now - timedelta(hours=3),
            scheduled_end=now - timedelta(hours=2),
            actual_start=now - timedelta(hours=3),
            actual_end=now - timedelta(hours=2),
            status="completed",
            participant_count=2,
        )
        session.add(meeting)

        completed_action = ActionItem(
            id=uuid.uuid4(),
            meeting_id=meeting.id,
            description="Write unit tests",
            assigned_to_name="Bob",
            status="completed",
            completed_at=now - timedelta(hours=1),
        )
        pending_action = ActionItem(
            id=uuid.uuid4(),
            meeting_id=meeting.id,
            description="Deploy to staging",
            assigned_to_name="Alice",
            status="pending",
        )
        session.add_all([completed_action, pending_action])
        await session.commit()

    return insight_session_factory


@pytest.mark.asyncio
async def test_meeting_time_analysis(seeded_insight_session_factory):
    """get_meeting_time_analysis returns correct meeting counts."""
    mock_ai = AsyncMock()
    svc = InsightService(ai_connector=mock_ai, db_session_factory=seeded_insight_session_factory)
    result = await svc.get_meeting_time_analysis(user_id="test-user-001", days=30)
    assert result["total_meetings"] == 1
    assert result["total_hours"] >= 0


@pytest.mark.asyncio
async def test_action_completion_stats(seeded_insight_session_factory):
    """get_action_completion_stats returns total, completed, and rate."""
    mock_ai = AsyncMock()
    svc = InsightService(ai_connector=mock_ai, db_session_factory=seeded_insight_session_factory)
    result = await svc.get_action_completion_stats(user_id="test-user-001", days=30)
    assert result["total"] == 2
    assert result["completed"] == 1
    assert result["rate"] == 50.0


@pytest.mark.asyncio
async def test_detect_conflicts_no_summary(seeded_insight_session_factory):
    """detect_conflicts returns empty list when no summary exists."""
    mock_ai = AsyncMock()
    svc = InsightService(ai_connector=mock_ai, db_session_factory=seeded_insight_session_factory)
    result = await svc.detect_conflicts(meeting_id=uuid.uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_collaboration_analysis_empty(insight_session_factory):
    """get_collaboration_analysis returns empty lists on no data."""
    mock_ai = AsyncMock()
    svc = InsightService(ai_connector=mock_ai, db_session_factory=insight_session_factory)
    result = await svc.get_collaboration_analysis(user_id="test-user-001", days=30)
    assert result["top_collaborators"] == []
    assert result["stale_contacts"] == []
    assert result["period_days"] == 30


@pytest.mark.asyncio
async def test_pattern_analysis_empty(insight_session_factory):
    """get_pattern_analysis returns empty lists on no data."""
    mock_ai = AsyncMock()
    svc = InsightService(ai_connector=mock_ai, db_session_factory=insight_session_factory)
    result = await svc.get_pattern_analysis(user_id="test-user-001", days=30)
    assert result["recurring_topics"] == []
    assert result["potential_reversals"] == []
    assert result["summaries_analyzed"] == 0
