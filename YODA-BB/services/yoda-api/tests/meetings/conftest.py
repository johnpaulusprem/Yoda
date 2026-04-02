"""Pytest fixtures for the Teams Meeting Assistant test suite.

Provides:
- test_settings: Settings object with test-safe values (SQLite in-memory DB)
- async_session: Async SQLAlchemy session using in-memory SQLite + aiosqlite
- mock_graph_client: AsyncMock for GraphClient
- test_client: httpx.AsyncClient wired to the FastAPI app
- sample_meeting: A pre-populated Meeting object
- sample_transcript_segments: A list of TranscriptSegment objects
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import StaticPool, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Settings fixture — overrides real settings with test-safe values
# ---------------------------------------------------------------------------

# Build test settings before importing app modules so that nothing
# accidentally reads production credentials.
_TEST_ENV = {
    "BASE_URL": "https://test.example.com",
    "DATABASE_URL": "sqlite+aiosqlite://",
    "AZURE_TENANT_ID": "test-tenant-id",
    "AZURE_CLIENT_ID": "test-client-id",
    "AZURE_CLIENT_SECRET": "test-client-secret",
    "AI_FOUNDRY_ENDPOINT": "https://test-ai.openai.azure.com/",
    "AI_FOUNDRY_API_KEY": "test-api-key",
    "AI_FOUNDRY_DEPLOYMENT_NAME": "gpt-4o-mini",
    "AI_FOUNDRY_DEPLOYMENT_NAME_COMPLEX": "gpt-4o",
    "BROWSER_BOT_BASE_URL": "http://localhost:3001",
    "BROWSER_BOT_API_KEY": "test-api-key",
    "INTER_SERVICE_HMAC_KEY": "test-hmac-key-for-testing",
    "REDIS_URL": "redis://localhost:6379/0",
    "DEBUG": "false",
    "NUDGE_ESCALATION_THRESHOLD": "2",
    "LONG_MEETING_THRESHOLD_MINUTES": "120",
}


@pytest.fixture
def test_settings():
    """Return a Settings instance with test values (in-memory SQLite DB)."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings

        return Settings()


# ---------------------------------------------------------------------------
# Async database session (in-memory SQLite with aiosqlite)
# ---------------------------------------------------------------------------

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
def test_session_factory(async_engine) -> async_sessionmaker:
    """Return an async_sessionmaker bound to the test engine.

    Services that accept a session_factory instead of a session should
    use this fixture so they create short-lived sessions per method call,
    backed by the same in-memory SQLite database (StaticPool).
    """
    return async_sessionmaker(async_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Mock external service clients
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_graph_client() -> AsyncMock:
    """AsyncMock for GraphClient with all public methods stubbed."""
    client = AsyncMock()
    client.create_calendar_subscription = AsyncMock(
        return_value={
            "id": "sub-test-001",
            "resource": "/users/test-user/events",
            "expirationDateTime": (
                datetime.now(timezone.utc) + timedelta(days=3)
            ).strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
        }
    )
    client.renew_subscription = AsyncMock(return_value={"id": "sub-test-001"})
    client.delete_subscription = AsyncMock(return_value=None)
    client.get_event = AsyncMock(return_value={})
    client.get_upcoming_events = AsyncMock(return_value=[])
    client.get_online_meeting = AsyncMock(return_value={})
    client.get_meeting_participants = AsyncMock(return_value=[])
    client.post_to_meeting_chat = AsyncMock(
        return_value={"id": "msg-001"}
    )
    client.send_proactive_message = AsyncMock(
        return_value={"id": "msg-002"}
    )
    client.search_user = AsyncMock(return_value=[])
    client.get_user = AsyncMock(return_value={})
    client.get_direct_reports = AsyncMock(return_value=[])
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_post_processing() -> AsyncMock:
    """AsyncMock for PostProcessingService."""
    service = AsyncMock()
    service.run = AsyncMock()
    return service


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_client(
    async_session: AsyncSession,
    mock_graph_client: AsyncMock,
    mock_post_processing: AsyncMock,
):
    """httpx.AsyncClient wired to the FastAPI app with mocked dependencies.

    Overrides:
    - get_db → yields the test async_session
    - Patches Settings so no real .env is needed
    - Skips the real lifespan (service initialization)
    """
    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI

    # Patch Settings before importing app modules that instantiate it
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        # Import a fresh app with the lifespan disabled so we don't need
        # real Azure credentials at import time.
        from meeting_service.routes.health import router as health_router
        from meeting_service.routes.meetings import router as meetings_router
        from meeting_service.routes.webhooks import router as webhooks_router
        from meeting_service.routes.action_items import router as action_items_router
        from meeting_service.routes.bot_events import router as bot_events_router
        from meeting_service.dependencies import get_db

        test_app = FastAPI(title="Test App")
        test_app.include_router(health_router, tags=["health"])
        test_app.include_router(
            webhooks_router, prefix="/webhooks", tags=["webhooks"]
        )
        test_app.include_router(
            meetings_router, prefix="/api/meetings", tags=["meetings"]
        )
        test_app.include_router(
            action_items_router,
            prefix="/api/action-items",
            tags=["action-items"],
        )
        test_app.include_router(
            bot_events_router,
            prefix="/api/bot-events",
            tags=["bot-events"],
        )

        from meeting_service.routes.sse import router as sse_router
        test_app.include_router(sse_router, tags=["sse"])

        # Wire up mock services on app.state
        from meeting_service.config import Settings

        test_app.state.settings = Settings()
        test_app.state.calendar_watcher = AsyncMock()
        test_app.state.post_processing = mock_post_processing
        test_app.state.graph_client = mock_graph_client

        # Override the DB dependency to return the test session
        async def override_get_db():
            yield async_session

        test_app.dependency_overrides[get_db] = override_get_db

        # Override auth to return a user dict with sub matching test data
        from meeting_service.utils.azure_ad_auth import get_current_user as meeting_get_current_user

        async def override_get_current_user():
            return {"sub": "aad-user-001", "name": "Alice Johnson", "roles": ["Admin"]}

        test_app.dependency_overrides[meeting_get_current_user] = override_get_current_user

        transport = ASGITransport(app=test_app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def sample_meeting(async_session: AsyncSession):
    """Create and return a sample Meeting in the test database."""
    from yoda_foundation.models.meeting import Meeting

    now = datetime.now(timezone.utc)
    meeting = Meeting(
        id=uuid.uuid4(),
        teams_meeting_id="teams-meeting-test-001",
        thread_id="19:meeting_test@thread.v2",
        join_url="https://teams.microsoft.com/l/meetup-join/test",
        subject="Test Sprint Planning",
        organizer_id="aad-user-001",
        organizer_name="Alice Johnson",
        organizer_email="alice@contoso.com",
        scheduled_start=now - timedelta(hours=2),
        scheduled_end=now - timedelta(hours=1),
        actual_start=now - timedelta(hours=2),
        actual_end=now - timedelta(hours=1),
        status="completed",
        acs_call_connection_id="acs-conn-test-12345",
        participant_count=3,
    )
    async_session.add(meeting)
    await async_session.commit()
    await async_session.refresh(meeting)
    return meeting


@pytest_asyncio.fixture
async def sample_transcript_segments(
    async_session: AsyncSession,
    sample_meeting,
):
    """Create and return a list of TranscriptSegments for the sample meeting."""
    from yoda_foundation.models.transcript import TranscriptSegment

    segments_data = [
        {
            "speaker_name": "Alice Johnson",
            "speaker_id": "aad-user-001",
            "text": "Let's start the sprint planning meeting.",
            "start_time": 0.0,
            "end_time": 4.5,
            "confidence": 0.96,
            "sequence_number": 0,
        },
        {
            "speaker_name": "Bob Williams",
            "speaker_id": "aad-user-002",
            "text": "We should prioritize the auth refactor.",
            "start_time": 5.0,
            "end_time": 9.5,
            "confidence": 0.94,
            "sequence_number": 1,
        },
        {
            "speaker_name": "Alice Johnson",
            "speaker_id": "aad-user-001",
            "text": "Agreed. Bob, can you take the lead on that?",
            "start_time": 10.0,
            "end_time": 14.0,
            "confidence": 0.95,
            "sequence_number": 2,
        },
        {
            "speaker_name": "Bob Williams",
            "speaker_id": "aad-user-002",
            "text": "Yes, I can handle it. Deadline is next Friday.",
            "start_time": 14.5,
            "end_time": 19.0,
            "confidence": 0.93,
            "sequence_number": 3,
        },
        {
            "speaker_name": "Alice Johnson",
            "speaker_id": "aad-user-001",
            "text": "Perfect. Let's wrap up. Thanks everyone!",
            "start_time": 19.5,
            "end_time": 23.0,
            "confidence": 0.97,
            "sequence_number": 4,
        },
    ]

    segments = []
    for data in segments_data:
        seg = TranscriptSegment(
            meeting_id=sample_meeting.id,
            **data,
        )
        async_session.add(seg)
        segments.append(seg)

    await async_session.commit()
    for seg in segments:
        await async_session.refresh(seg)

    return segments
