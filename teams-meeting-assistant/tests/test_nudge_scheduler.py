"""Tests for the NudgeScheduler service.

Covers:
- Items approaching deadline get nudged
- Items past escalation threshold get escalated to the organizer
- Snoozed items are skipped until the snooze expires
- Completed items are not nudged
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

async def _create_action_item(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    status: str = "pending",
    deadline_hours_from_now: float = 12,
    nudge_count: int = 0,
    last_nudged_hours_ago: float | None = None,
    snoozed_until: datetime | None = None,
    assigned_to_user_id: str = "aad-user-002",
):
    """Create an ActionItem in the test DB."""
    from app.models.action_item import ActionItem

    now = datetime.now(timezone.utc)
    item = ActionItem(
        meeting_id=meeting_id,
        description=f"Test action item ({status}, {nudge_count} nudges)",
        assigned_to_name="Bob Williams",
        assigned_to_user_id=assigned_to_user_id,
        assigned_to_email="bob@contoso.com",
        deadline=now + timedelta(hours=deadline_hours_from_now),
        priority="high",
        status=status,
        nudge_count=nudge_count,
        last_nudged_at=(
            now - timedelta(hours=last_nudged_hours_ago)
            if last_nudged_hours_ago is not None
            else None
        ),
        snoozed_until=snoozed_until,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Test: Nudge approaching deadline
# ---------------------------------------------------------------------------

async def test_nudge_approaching_deadline(
    async_session: AsyncSession,
    sample_meeting,
):
    """Items with a deadline within 24 hours should receive a nudge."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.nudge_scheduler import NudgeScheduler

        settings = Settings()
        mock_delivery = AsyncMock()
        mock_delivery.send_nudge = AsyncMock()
        mock_delivery.send_escalation = AsyncMock()

        # Create an action item with a deadline 12 hours from now (within 24h threshold)
        item = await _create_action_item(
            async_session,
            sample_meeting.id,
            status="pending",
            deadline_hours_from_now=12,
            nudge_count=0,
            last_nudged_hours_ago=None,
        )

        scheduler = NudgeScheduler(
            delivery=mock_delivery,
            db=async_session,
            settings=settings,
        )

        await scheduler.run()

        # Should have sent a nudge
        mock_delivery.send_nudge.assert_called_once()
        nudged_item = mock_delivery.send_nudge.call_args[0][0]
        assert nudged_item.id == item.id


# ---------------------------------------------------------------------------
# Test: Escalation after threshold
# ---------------------------------------------------------------------------

async def test_escalation_after_threshold(
    async_session: AsyncSession,
    sample_meeting,
):
    """Items that have been nudged >= NUDGE_ESCALATION_THRESHOLD times should be escalated."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.nudge_scheduler import NudgeScheduler

        settings = Settings()
        # Threshold is 2 based on test settings
        mock_delivery = AsyncMock()
        mock_delivery.send_nudge = AsyncMock()
        mock_delivery.send_escalation = AsyncMock()

        # Create an item that has already been nudged twice (at threshold)
        item = await _create_action_item(
            async_session,
            sample_meeting.id,
            status="pending",
            deadline_hours_from_now=6,  # within threshold
            nudge_count=2,  # at escalation threshold
            last_nudged_hours_ago=5,  # past the 4-hour cooldown
        )

        scheduler = NudgeScheduler(
            delivery=mock_delivery,
            db=async_session,
            settings=settings,
        )

        await scheduler.run()

        # Should have escalated, not just nudged
        mock_delivery.send_escalation.assert_called_once()
        mock_delivery.send_nudge.assert_not_called()

        escalated_item = mock_delivery.send_escalation.call_args[0][0]
        assert escalated_item.id == item.id


# ---------------------------------------------------------------------------
# Test: Snoozed items skipped
# ---------------------------------------------------------------------------

async def test_snoozed_items_skipped(
    async_session: AsyncSession,
    sample_meeting,
):
    """Items with snoozed_until in the future should NOT be nudged."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.nudge_scheduler import NudgeScheduler

        settings = Settings()
        mock_delivery = AsyncMock()
        mock_delivery.send_nudge = AsyncMock()
        mock_delivery.send_escalation = AsyncMock()

        now = datetime.now(timezone.utc)

        # Create a snoozed item (snoozed until tomorrow)
        item = await _create_action_item(
            async_session,
            sample_meeting.id,
            status="pending",
            deadline_hours_from_now=6,
            nudge_count=0,
            last_nudged_hours_ago=None,
            snoozed_until=now + timedelta(days=1),  # snoozed until tomorrow
        )

        scheduler = NudgeScheduler(
            delivery=mock_delivery,
            db=async_session,
            settings=settings,
        )

        await scheduler.run()

        # Neither nudge nor escalation should have been sent
        mock_delivery.send_nudge.assert_not_called()
        mock_delivery.send_escalation.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Completed items not nudged
# ---------------------------------------------------------------------------

async def test_completed_items_not_nudged(
    async_session: AsyncSession,
    sample_meeting,
):
    """Items with status='completed' should never be nudged."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from app.config import Settings
        from app.services.nudge_scheduler import NudgeScheduler

        settings = Settings()
        mock_delivery = AsyncMock()
        mock_delivery.send_nudge = AsyncMock()
        mock_delivery.send_escalation = AsyncMock()

        # Create a completed item with an upcoming deadline
        item = await _create_action_item(
            async_session,
            sample_meeting.id,
            status="completed",
            deadline_hours_from_now=6,
            nudge_count=0,
            last_nudged_hours_ago=None,
        )

        scheduler = NudgeScheduler(
            delivery=mock_delivery,
            db=async_session,
            settings=settings,
        )

        await scheduler.run()

        # Neither nudge nor escalation should have been sent
        mock_delivery.send_nudge.assert_not_called()
        mock_delivery.send_escalation.assert_not_called()
