"""Pytest fixtures for the weekly digest service test suite."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_TEST_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite://",
    "AZURE_TENANT_ID": "test-tenant-id",
    "AZURE_CLIENT_ID": "test-client-id",
    "AZURE_CLIENT_SECRET": "test-client-secret",
    "AI_FOUNDRY_ENDPOINT": "https://test-ai.openai.azure.com/",
    "AI_FOUNDRY_API_KEY": "test-api-key",
    "REDIS_URL": "",
    "DEBUG": "false",
    "DIGEST_USER_IDS": "",
}


@pytest.fixture
def test_settings():
    """Return a Settings instance with test values."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from weekly_digest_service.config import Settings
        return Settings()


@pytest_asyncio.fixture
async def async_engine():
    """Create an in-memory SQLite async engine with tables."""
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
async def async_session_factory(async_engine):
    """Return an async session factory for tests."""
    return async_sessionmaker(async_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def async_session(async_session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session backed by in-memory SQLite."""
    async with async_session_factory() as session:
        yield session


@pytest.fixture
def mock_ai_connector() -> AsyncMock:
    """AsyncMock for AI connector."""
    connector = AsyncMock()
    connector.complete = AsyncMock(
        return_value=(
            "This week saw 5 productive meetings with a strong completion rate. "
            "Key decisions were made around the Q4 budget allocation and hiring plan. "
            "Looking ahead, the team should focus on closing open action items before the deadline."
        )
    )
    return connector


@pytest.fixture
def mock_delivery_service() -> AsyncMock:
    """AsyncMock for delivery service."""
    service = AsyncMock()
    service.send_adaptive_card = AsyncMock(return_value={"id": "msg-001"})
    return service


@pytest_asyncio.fixture
async def seed_weekly_data(async_session: AsyncSession):
    """Seed a week's worth of meetings and action items for digest generation."""
    from yoda_foundation.models.meeting import Meeting, MeetingParticipant
    from yoda_foundation.models.action_item import ActionItem
    from yoda_foundation.models.summary import MeetingSummary

    now = datetime.now(timezone.utc)

    # Create 3 completed meetings
    meetings = []
    for i in range(3):
        meeting = Meeting(
            id=uuid.uuid4(),
            teams_meeting_id=f"teams-meeting-digest-{i:03d}",
            thread_id=f"19:meeting_digest_{i}@thread.v2",
            join_url=f"https://teams.microsoft.com/l/meetup-join/digest{i}",
            subject=f"Meeting {i + 1}: {'Budget Review' if i == 0 else 'Sprint Planning' if i == 1 else 'Architecture'}",
            organizer_id="aad-user-001",
            organizer_name="Alice Johnson",
            organizer_email="alice@contoso.com",
            scheduled_start=now - timedelta(days=i + 1),
            scheduled_end=now - timedelta(days=i + 1) + timedelta(hours=1),
            actual_start=now - timedelta(days=i + 1),
            actual_end=now - timedelta(days=i + 1) + timedelta(hours=1),
            status="completed",
            participant_count=2,
        )
        async_session.add(meeting)
        await async_session.flush()

        # Add participants
        p1 = MeetingParticipant(
            meeting_id=meeting.id,
            user_id="aad-user-001",
            display_name="Alice Johnson",
            email="alice@contoso.com",
            role="organizer",
        )
        p2 = MeetingParticipant(
            meeting_id=meeting.id,
            user_id="aad-user-002",
            display_name="Bob Williams",
            email="bob@contoso.com",
            role="attendee",
        )
        async_session.add_all([p1, p2])

        # Add summary with decisions
        summary = MeetingSummary(
            meeting_id=meeting.id,
            summary_text=f"Summary for meeting {i + 1}",
            key_topics=[{"topic": "topic1"}, {"topic": "topic2"}],
            decisions=[{"decision": f"Decision {i + 1}: Approve budget"}],
            model_used="gpt-4o-mini",
            processing_time_seconds=1.5,
        )
        async_session.add(summary)
        meetings.append(meeting)

    # Add action items
    for i, status in enumerate(["completed", "pending", "in_progress"]):
        item = ActionItem(
            meeting_id=meetings[0].id,
            description=f"Action item {i + 1}",
            assigned_to_name="Bob Williams",
            assigned_to_user_id="aad-user-002",
            status=status,
            deadline=now + timedelta(days=3),
        )
        async_session.add(item)

    await async_session.commit()
    return meetings
