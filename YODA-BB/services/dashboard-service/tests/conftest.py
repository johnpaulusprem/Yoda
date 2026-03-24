"""Pytest fixtures for the dashboard service test suite.

Provides:
- test_settings: Settings object with test-safe values (SQLite in-memory DB)
- async_session: Async SQLAlchemy session using in-memory SQLite + aiosqlite
- test_client: httpx.AsyncClient wired to the FastAPI app
- sample_meeting: A pre-populated Meeting object
- sample_action_items: Pre-populated ActionItem objects
- sample_notification: A pre-populated Notification object
"""

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

# ---------------------------------------------------------------------------
# Settings fixture -- overrides real settings with test-safe values
# ---------------------------------------------------------------------------

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
}


@pytest.fixture
def test_settings():
    """Return a Settings instance with test values (in-memory SQLite DB)."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from dashboard_service.config import Settings

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


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_client(async_session: AsyncSession):
    """httpx.AsyncClient wired to the FastAPI app with mocked dependencies."""
    from httpx import ASGITransport, AsyncClient
    from fastapi import FastAPI

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from dashboard_service.routes.health import router as health_router
        from dashboard_service.routes.dashboard import router as dashboard_router
        from dashboard_service.routes.insights import router as insights_router
        from dashboard_service.routes.notifications import router as notifications_router
        from dashboard_service.routes.search import router as search_router
        from dashboard_service.routes.user_settings import router as user_settings_router
        from dashboard_service.dependencies import get_db

        test_app = FastAPI(title="Test Dashboard App")
        test_app.include_router(health_router, tags=["health"])
        test_app.include_router(
            dashboard_router, prefix="/api/dashboard", tags=["dashboard"]
        )
        test_app.include_router(
            insights_router, prefix="/api/insights", tags=["insights"]
        )
        test_app.include_router(
            notifications_router, prefix="/api/notifications", tags=["notifications"]
        )
        test_app.include_router(
            search_router, prefix="/api/search", tags=["search"]
        )
        test_app.include_router(
            user_settings_router, prefix="/api/settings", tags=["settings"]
        )

        from dashboard_service.config import Settings

        test_app.state.settings = Settings()

        # Override the DB dependency to return the test session
        async def override_get_db():
            yield async_session

        test_app.dependency_overrides[get_db] = override_get_db

        # Override auth to return a fake security context
        from yoda_foundation.security.auth_dependency import get_current_user
        from yoda_foundation.security.context import SecurityContext

        mock_ctx = SecurityContext(
            user_id="test-user-001",
            tenant_id="test-tenant-id",
            roles=["Admin"],
        )

        test_app.dependency_overrides[get_current_user] = lambda: mock_ctx

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
        organizer_id="test-user-001",
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
async def sample_action_items(async_session: AsyncSession, sample_meeting):
    """Create and return sample ActionItems for the test meeting."""
    from yoda_foundation.models.action_item import ActionItem

    now = datetime.now(timezone.utc)
    items = []

    # Pending item (due soon)
    pending = ActionItem(
        id=uuid.uuid4(),
        meeting_id=sample_meeting.id,
        description="Review the auth refactor PR",
        assigned_to_name="Bob Williams",
        assigned_to_user_id="test-user-002",
        assigned_to_email="bob@contoso.com",
        deadline=now + timedelta(hours=24),
        priority="high",
        status="pending",
    )
    async_session.add(pending)
    items.append(pending)

    # Overdue item
    overdue = ActionItem(
        id=uuid.uuid4(),
        meeting_id=sample_meeting.id,
        description="Submit quarterly report",
        assigned_to_name="Alice Johnson",
        assigned_to_user_id="test-user-001",
        assigned_to_email="alice@contoso.com",
        deadline=now - timedelta(days=2),
        priority="high",
        status="pending",
    )
    async_session.add(overdue)
    items.append(overdue)

    # Completed item
    completed = ActionItem(
        id=uuid.uuid4(),
        meeting_id=sample_meeting.id,
        description="Update project timeline",
        assigned_to_name="Alice Johnson",
        assigned_to_user_id="test-user-001",
        assigned_to_email="alice@contoso.com",
        deadline=now - timedelta(days=1),
        priority="medium",
        status="completed",
        completed_at=now - timedelta(hours=12),
    )
    async_session.add(completed)
    items.append(completed)

    await async_session.commit()
    for item in items:
        await async_session.refresh(item)

    return items


@pytest_asyncio.fixture
async def sample_notification(async_session: AsyncSession, sample_meeting):
    """Create and return a sample Notification."""
    from yoda_foundation.models.notification import Notification

    notification = Notification(
        id=uuid.uuid4(),
        user_id="test-user-001",
        type="summary_ready",
        title="Summary ready",
        message="Your meeting summary is ready for review.",
        read=False,
        related_entity_type="meeting",
        related_entity_id=sample_meeting.id,
    )
    async_session.add(notification)
    await async_session.commit()
    await async_session.refresh(notification)
    return notification
