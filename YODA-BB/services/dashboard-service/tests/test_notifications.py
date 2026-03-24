"""Tests for notification service and routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dashboard_service.services.notification_service import NotificationService


@pytest_asyncio.fixture
async def notif_engine():
    """Create a dedicated in-memory SQLite engine for notification tests."""
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
async def notif_session_factory(notif_engine):
    """Session factory for NotificationService."""
    return async_sessionmaker(notif_engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_create_notification(notif_session_factory):
    """NotificationService.create persists a notification."""
    svc = NotificationService(db_session_factory=notif_session_factory)
    notification = await svc.create(
        user_id="test-user-001",
        type="summary_ready",
        title="Summary ready",
        message="Your meeting summary is available.",
    )
    assert notification.id is not None
    assert notification.user_id == "test-user-001"
    assert notification.type == "summary_ready"
    assert notification.read is False


@pytest.mark.asyncio
async def test_get_for_user(notif_session_factory):
    """get_for_user retrieves notifications for a given user."""
    svc = NotificationService(db_session_factory=notif_session_factory)
    await svc.create(
        user_id="test-user-001",
        type="action_due",
        title="Action due",
        message="You have an action item due.",
    )
    await svc.create(
        user_id="test-user-002",
        type="nudge",
        title="Nudge",
        message="Please complete your task.",
    )
    notifications = await svc.get_for_user("test-user-001")
    assert len(notifications) == 1
    assert notifications[0].user_id == "test-user-001"


@pytest.mark.asyncio
async def test_get_unread_count(notif_session_factory):
    """get_unread_count returns the number of unread notifications."""
    svc = NotificationService(db_session_factory=notif_session_factory)
    await svc.create(
        user_id="test-user-001",
        type="summary_ready",
        title="Summary 1",
        message="First summary.",
    )
    await svc.create(
        user_id="test-user-001",
        type="summary_ready",
        title="Summary 2",
        message="Second summary.",
    )
    count = await svc.get_unread_count("test-user-001")
    assert count == 2


@pytest.mark.asyncio
async def test_mark_read(notif_session_factory):
    """mark_read sets the notification's read flag to True."""
    svc = NotificationService(db_session_factory=notif_session_factory)
    notification = await svc.create(
        user_id="test-user-001",
        type="nudge",
        title="Nudge",
        message="Please act.",
    )
    await svc.mark_read(notification.id)
    # Re-fetch
    notifications = await svc.get_for_user("test-user-001", read=True)
    assert len(notifications) == 1
    assert notifications[0].read is True


@pytest.mark.asyncio
async def test_mark_all_read(notif_session_factory):
    """mark_all_read marks all notifications for a user as read."""
    svc = NotificationService(db_session_factory=notif_session_factory)
    await svc.create(
        user_id="test-user-001",
        type="summary_ready",
        title="S1",
        message="First.",
    )
    await svc.create(
        user_id="test-user-001",
        type="summary_ready",
        title="S2",
        message="Second.",
    )
    count = await svc.mark_all_read("test-user-001")
    assert count == 2
    unread = await svc.get_unread_count("test-user-001")
    assert unread == 0
