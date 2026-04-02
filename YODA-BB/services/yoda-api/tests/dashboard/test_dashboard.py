"""Tests for dashboard aggregate queries and dashboard service."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard_service.services.dashboard_service import (
    DashboardService,
    DashboardStats,
    AttentionItem,
    ActivityItem,
)


@pytest.mark.asyncio
async def test_get_stats_empty_db(async_session: AsyncSession):
    """DashboardService.get_stats returns zeros on an empty database."""
    svc = DashboardService(db=async_session)
    stats = await svc.get_stats(user_id="nonexistent-user")
    assert isinstance(stats, DashboardStats)
    assert stats.meetings_today == 0
    assert stats.pending_actions == 0
    assert stats.overdue_actions == 0
    assert stats.completion_rate == 0.0
    assert stats.total_meetings_processed == 0


@pytest.mark.asyncio
async def test_get_stats_with_data(async_session: AsyncSession, sample_meeting, sample_action_items):
    """DashboardService.get_stats returns correct counts with seeded data."""
    svc = DashboardService(db=async_session)
    stats = await svc.get_stats(user_id="test-user-001")
    # test-user-001 has 1 completed meeting, 1 overdue action item, 1 completed action item
    assert stats.total_meetings_processed == 1
    assert stats.overdue_actions >= 1
    assert stats.completed_actions >= 1


@pytest.mark.asyncio
async def test_get_attention_items_empty(async_session: AsyncSession):
    """get_attention_items returns an empty list on an empty database."""
    svc = DashboardService(db=async_session)
    items = await svc.get_attention_items(user_id="nonexistent-user")
    assert items == []


@pytest.mark.asyncio
async def test_get_attention_items_with_overdue(async_session: AsyncSession, sample_meeting, sample_action_items):
    """get_attention_items includes overdue action items for the user."""
    svc = DashboardService(db=async_session)
    items = await svc.get_attention_items(user_id="test-user-001")
    overdue_items = [i for i in items if i.item_type == "overdue_action"]
    assert len(overdue_items) >= 1
    assert overdue_items[0].severity == "high"


@pytest.mark.asyncio
async def test_get_activity_feed_empty(async_session: AsyncSession):
    """get_activity_feed returns an empty list on an empty database."""
    svc = DashboardService(db=async_session)
    feed = await svc.get_activity_feed(user_id="nonexistent-user")
    assert feed == []


@pytest.mark.asyncio
async def test_get_activity_feed_with_completed_meeting(async_session: AsyncSession, sample_meeting):
    """get_activity_feed includes recently completed meetings."""
    svc = DashboardService(db=async_session)
    feed = await svc.get_activity_feed(user_id="test-user-001")
    meeting_activities = [a for a in feed if a.activity_type == "meeting_completed"]
    assert len(meeting_activities) >= 1
    assert "Sprint Planning" in meeting_activities[0].title


@pytest.mark.asyncio
async def test_attention_items_sorted_by_severity(async_session: AsyncSession, sample_meeting, sample_action_items):
    """Attention items are sorted with high severity first."""
    svc = DashboardService(db=async_session)
    items = await svc.get_attention_items(user_id="test-user-001")
    if len(items) >= 2:
        severity_order = {"high": 0, "medium": 1, "low": 2}
        for i in range(len(items) - 1):
            assert severity_order.get(items[i].severity, 3) <= severity_order.get(
                items[i + 1].severity, 3
            )
