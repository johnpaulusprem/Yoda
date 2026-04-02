"""Pytest fixtures for the pre-meeting brief service test suite."""

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
}


@pytest.fixture
def test_settings():
    """Return a Settings instance with test values."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from pre_meeting_brief_service.config import Settings
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
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session backed by in-memory SQLite."""
    session_factory = async_sessionmaker(
        async_engine, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
def mock_graph_client() -> AsyncMock:
    """AsyncMock for GraphClient with brief-relevant methods stubbed."""
    client = AsyncMock()
    client.get_user = AsyncMock(return_value={
        "jobTitle": "VP Engineering",
        "department": "Engineering",
    })
    client.get_recent_files = AsyncMock(return_value=[
        {"name": "Q4 Report.docx", "webUrl": "https://sharepoint.com/q4"},
        {"name": "Architecture.pptx", "webUrl": "https://sharepoint.com/arch"},
    ])
    client.get_user_emails = AsyncMock(return_value=[
        {
            "subject": "Budget Review Follow-up",
            "from": {"emailAddress": {"address": "bob@contoso.com", "name": "Bob"}},
            "toRecipients": [{"emailAddress": {"address": "alice@contoso.com"}}],
            "bodyPreview": "Hi Alice, following up on the budget discussion...",
            "receivedDateTime": "2026-03-09T10:00:00Z",
        },
    ])
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_ai_connector() -> AsyncMock:
    """AsyncMock for AI connector."""
    connector = AsyncMock()
    connector.complete = AsyncMock(
        return_value='{"questions": ["What is the status of Q4 targets?", "Are there any blockers?"]}'
    )
    return connector


@pytest_asyncio.fixture
async def sample_meeting_with_participants(async_session: AsyncSession):
    """Create a meeting with participants."""
    from yoda_foundation.models.meeting import Meeting, MeetingParticipant

    now = datetime.now(timezone.utc)
    meeting = Meeting(
        id=uuid.uuid4(),
        teams_meeting_id="teams-meeting-brief-001",
        thread_id="19:meeting_brief@thread.v2",
        join_url="https://teams.microsoft.com/l/meetup-join/brief",
        subject="Q4 Budget Review",
        organizer_id="aad-user-001",
        organizer_name="Alice Johnson",
        organizer_email="alice@contoso.com",
        scheduled_start=now + timedelta(hours=1),
        scheduled_end=now + timedelta(hours=2),
        status="scheduled",
        participant_count=2,
    )
    async_session.add(meeting)
    await async_session.flush()

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
    await async_session.commit()
    await async_session.refresh(meeting)
    return meeting
