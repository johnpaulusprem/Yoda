"""Tests for the CalendarWatcher service.

Covers:
- Webhook validation (returns validationToken)
- New meeting created via webhook -> stored in DB + join scheduled
- Meeting updated via webhook -> DB updated
- Meeting deleted via webhook -> cancelled
- setup_subscriptions for opted-in users
- renew_subscriptions for expiring subscriptions
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import _TEST_ENV

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _graph_event(event_id: str = "evt-001", subject: str = "Sprint Planning") -> dict:
    """Build a mock Graph event dict as returned by GraphClient.get_event."""
    now = datetime.now(timezone.utc)
    return {
        "id": event_id,
        "subject": subject,
        "isOnlineMeeting": True,
        "onlineMeeting": {
            "joinUrl": "https://teams.microsoft.com/l/meetup-join/19%3ameeting_test%40thread.v2/0",
            "joinMeetingIdSettings": {"joinMeetingId": event_id},
        },
        "start": {
            "dateTime": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.0000000"),
            "timeZone": "UTC",
        },
        "end": {
            "dateTime": (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.0000000"),
            "timeZone": "UTC",
        },
        "organizer": {
            "emailAddress": {
                "name": "Alice Johnson",
                "address": "alice@contoso.com",
            }
        },
    }


def _webhook_payload(
    change_type: str = "created",
    resource: str = "users/aad-user-001/events/evt-001",
    subscription_id: str = "sub-001",
) -> dict:
    """Build a Graph webhook POST payload."""
    return {
        "value": [
            {
                "subscriptionId": subscription_id,
                "changeType": change_type,
                "resource": resource,
                "resourceData": {
                    "@odata.type": "#Microsoft.Graph.Event",
                    "@odata.id": resource,
                    "id": resource.split("/")[-1],
                },
                "tenantId": "test-tenant-id",
            }
        ]
    }


# ---------------------------------------------------------------------------
# Test: Webhook validation returns token
# ---------------------------------------------------------------------------

async def test_webhook_validation_returns_token(test_client):
    """When Graph sends a validation request, the endpoint echoes the token."""
    response = await test_client.post(
        "/webhooks/graph?validationToken=abc-validation-token-123"
    )
    assert response.status_code == 200
    assert response.text == "abc-validation-token-123"
    assert response.headers["content-type"].startswith("text/plain")


# ---------------------------------------------------------------------------
# Test: handle_webhook creates meeting
# ---------------------------------------------------------------------------

async def test_handle_webhook_creates_meeting(
    async_session: AsyncSession,
    test_session_factory: async_sessionmaker,
    mock_graph_client: AsyncMock,
):
    """A 'created' webhook should store the meeting in the DB and schedule a join."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from yoda_foundation.models.meeting import Meeting
        from meeting_service.services.calendar_watcher import CalendarWatcher

        settings = Settings()
        scheduler = MagicMock()
        scheduler.add_job = MagicMock()

        mock_graph_client.get_event = AsyncMock(
            return_value=_graph_event("evt-new-001", "New Meeting")
        )

        watcher = CalendarWatcher(
            graph_client=mock_graph_client,
            session_factory=test_session_factory,
            scheduler=scheduler,
            settings=settings,
        )

        payload = _webhook_payload(
            change_type="created",
            resource="users/aad-user-001/events/evt-new-001",
        )
        await watcher.handle_webhook(payload)

        # Verify meeting was created in DB
        result = await async_session.execute(
            select(Meeting).where(Meeting.teams_meeting_id == "evt-new-001")
        )
        meeting = result.scalar_one_or_none()

        assert meeting is not None
        assert meeting.subject == "New Meeting"
        assert meeting.status == "scheduled"
        assert meeting.organizer_name == "Alice Johnson"
        assert meeting.organizer_email == "alice@contoso.com"

        # Verify scheduler was called to schedule a bot join
        scheduler.add_job.assert_called_once()
        call_kwargs = scheduler.add_job.call_args
        assert call_kwargs.kwargs.get("id", call_kwargs[1].get("id", "")).startswith("join_")


# ---------------------------------------------------------------------------
# Test: handle_webhook updates meeting
# ---------------------------------------------------------------------------

async def test_handle_webhook_updates_meeting(
    async_session: AsyncSession,
    test_session_factory: async_sessionmaker,
    mock_graph_client: AsyncMock,
):
    """An 'updated' webhook should update the meeting's details in the DB."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from yoda_foundation.models.meeting import Meeting
        from meeting_service.services.calendar_watcher import CalendarWatcher

        settings = Settings()
        scheduler = MagicMock()
        scheduler.add_job = MagicMock()
        scheduler.remove_job = MagicMock()

        # First, create the meeting via a 'created' notification
        mock_graph_client.get_event = AsyncMock(
            return_value=_graph_event("evt-upd-001", "Original Subject")
        )

        watcher = CalendarWatcher(
            graph_client=mock_graph_client,
            session_factory=test_session_factory,
            scheduler=scheduler,
            settings=settings,
        )

        create_payload = _webhook_payload(
            change_type="created",
            resource="users/aad-user-001/events/evt-upd-001",
        )
        await watcher.handle_webhook(create_payload)

        # Now send an 'updated' notification with a changed subject
        updated_event = _graph_event("evt-upd-001", "Updated Subject")
        mock_graph_client.get_event = AsyncMock(return_value=updated_event)

        update_payload = _webhook_payload(
            change_type="updated",
            resource="users/aad-user-001/events/evt-upd-001",
        )
        await watcher.handle_webhook(update_payload)

        # Verify meeting was updated
        result = await async_session.execute(
            select(Meeting).where(Meeting.teams_meeting_id == "evt-upd-001")
        )
        meeting = result.scalar_one()
        assert meeting.subject == "Updated Subject"


# ---------------------------------------------------------------------------
# Test: handle_webhook cancels deleted meeting
# ---------------------------------------------------------------------------

async def test_handle_webhook_cancels_deleted_meeting(
    async_session: AsyncSession,
    test_session_factory: async_sessionmaker,
    mock_graph_client: AsyncMock,
):
    """A 'deleted' webhook should cancel the meeting and remove the scheduled join."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from yoda_foundation.models.meeting import Meeting
        from meeting_service.services.calendar_watcher import CalendarWatcher

        settings = Settings()
        scheduler = MagicMock()
        scheduler.add_job = MagicMock()
        scheduler.remove_job = MagicMock()

        # Create the meeting first
        mock_graph_client.get_event = AsyncMock(
            return_value=_graph_event("evt-del-001", "Meeting to Delete")
        )

        watcher = CalendarWatcher(
            graph_client=mock_graph_client,
            session_factory=test_session_factory,
            scheduler=scheduler,
            settings=settings,
        )

        create_payload = _webhook_payload(
            change_type="created",
            resource="users/aad-user-001/events/evt-del-001",
        )
        await watcher.handle_webhook(create_payload)

        # Verify meeting exists
        result = await async_session.execute(
            select(Meeting).where(Meeting.teams_meeting_id == "evt-del-001")
        )
        meeting = result.scalar_one()
        assert meeting.status == "scheduled"

        # Now send a 'deleted' notification
        delete_payload = _webhook_payload(
            change_type="deleted",
            resource="users/aad-user-001/events/evt-del-001",
        )
        await watcher.handle_webhook(delete_payload)

        # Verify meeting was cancelled
        await async_session.refresh(meeting)
        assert meeting.status == "cancelled"

        # Verify scheduler was asked to remove the job
        scheduler.remove_job.assert_called()


# ---------------------------------------------------------------------------
# Test: setup_subscriptions for opted-in users
# ---------------------------------------------------------------------------

async def test_setup_subscriptions_for_opted_in_users(
    async_session: AsyncSession,
    test_session_factory: async_sessionmaker,
    mock_graph_client: AsyncMock,
):
    """setup_subscriptions should create Graph subscriptions for opted-in users."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from yoda_foundation.models.subscription import UserPreference, GraphSubscription
        from meeting_service.services.calendar_watcher import CalendarWatcher

        settings = Settings()
        scheduler = MagicMock()

        # Add opted-in users
        user1 = UserPreference(
            user_id="user-opt-in-1",
            display_name="Opted In User 1",
            email="user1@contoso.com",
            opted_in=True,
        )
        user2 = UserPreference(
            user_id="user-opt-in-2",
            display_name="Opted In User 2",
            email="user2@contoso.com",
            opted_in=True,
        )
        user3 = UserPreference(
            user_id="user-opt-out",
            display_name="Opted Out User",
            email="user3@contoso.com",
            opted_in=False,
        )
        async_session.add_all([user1, user2, user3])
        await async_session.commit()

        # Set up the mock to return subscription data
        mock_graph_client.create_calendar_subscription = AsyncMock(
            side_effect=[
                {
                    "id": "sub-for-user1",
                    "resource": "/users/user-opt-in-1/events",
                    "expirationDateTime": "2026-03-06T10:00:00.0000000Z",
                },
                {
                    "id": "sub-for-user2",
                    "resource": "/users/user-opt-in-2/events",
                    "expirationDateTime": "2026-03-06T10:00:00.0000000Z",
                },
            ]
        )

        watcher = CalendarWatcher(
            graph_client=mock_graph_client,
            session_factory=test_session_factory,
            scheduler=scheduler,
            settings=settings,
        )

        await watcher.setup_subscriptions()

        # Should have called create_calendar_subscription for both opted-in users
        assert mock_graph_client.create_calendar_subscription.call_count == 2

        # Verify subscriptions are stored in DB
        result = await async_session.execute(
            select(GraphSubscription).where(
                GraphSubscription.status == "active"
            )
        )
        subs = result.scalars().all()
        assert len(subs) == 2

        sub_user_ids = {s.user_id for s in subs}
        assert sub_user_ids == {"user-opt-in-1", "user-opt-in-2"}


# ---------------------------------------------------------------------------
# Test: renew_expiring_subscriptions
# ---------------------------------------------------------------------------

async def test_renew_expiring_subscriptions(
    async_session: AsyncSession,
    test_session_factory: async_sessionmaker,
    mock_graph_client: AsyncMock,
):
    """renew_subscriptions should renew subscriptions expiring within 6 hours."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from yoda_foundation.models.subscription import GraphSubscription
        from meeting_service.services.calendar_watcher import CalendarWatcher

        settings = Settings()
        scheduler = MagicMock()
        now = datetime.now(timezone.utc)

        # Create an expiring subscription (within 6 hours)
        expiring_sub = GraphSubscription(
            subscription_id="sub-expiring",
            user_id="user-001",
            resource="/users/user-001/events",
            expiration=now + timedelta(hours=3),  # expires in 3 hours
            status="active",
        )
        # Create a non-expiring subscription
        healthy_sub = GraphSubscription(
            subscription_id="sub-healthy",
            user_id="user-002",
            resource="/users/user-002/events",
            expiration=now + timedelta(days=2),  # plenty of time left
            status="active",
        )
        async_session.add_all([expiring_sub, healthy_sub])
        await async_session.commit()

        watcher = CalendarWatcher(
            graph_client=mock_graph_client,
            session_factory=test_session_factory,
            scheduler=scheduler,
            settings=settings,
        )

        await watcher.renew_subscriptions()

        # Only the expiring subscription should have been renewed
        mock_graph_client.renew_subscription.assert_called_once()
        call_args = mock_graph_client.renew_subscription.call_args
        assert call_args.kwargs.get(
            "subscription_id", call_args[1].get("subscription_id")
        ) == "sub-expiring" or call_args[0][0] == "sub-expiring"

        # Verify the expiration was extended in the DB
        await async_session.refresh(expiring_sub)
        exp = expiring_sub.expiration
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        assert exp > now + timedelta(hours=6)
