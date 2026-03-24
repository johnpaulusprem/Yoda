"""Tests for the Delivery Service.

Covers:
- deliver_summary posts an Adaptive Card to the meeting chat
- deliver_summary marks the summary as delivered with a timestamp
- send_nudge updates nudge tracking fields on the action item
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from tests.conftest import _TEST_ENV

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_meeting():
    """Create a mock Meeting object."""
    meeting = MagicMock()
    meeting.id = uuid.uuid4()
    meeting.subject = "Sprint Planning"
    meeting.thread_id = "19:meeting_test@thread.v2"
    meeting.organizer_id = "aad-user-001"
    meeting.organizer_name = "Alice Johnson"
    meeting.organizer_email = "alice@contoso.com"
    meeting.scheduled_start = datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc)
    meeting.scheduled_end = datetime(2026, 3, 3, 11, 0, tzinfo=timezone.utc)
    meeting.actual_start = datetime(2026, 3, 3, 10, 1, tzinfo=timezone.utc)
    meeting.actual_end = datetime(2026, 3, 3, 10, 58, tzinfo=timezone.utc)
    meeting.participant_count = 3
    return meeting


def _make_summary(meeting_id: uuid.UUID):
    """Create a mock MeetingSummary object."""
    summary = MagicMock()
    summary.id = uuid.uuid4()
    summary.meeting_id = meeting_id
    summary.summary_text = "The team discussed sprint 23 planning and prioritized tasks."
    summary.decisions = [
        {"decision": "Use URL-based versioning", "context": "Easier to test."}
    ]
    summary.key_topics = [
        {"topic": "Auth Refactor", "timestamp": "00:05", "detail": "Top priority."}
    ]
    summary.unresolved_questions = ["Who will handle staging access?"]
    summary.model_used = "gpt-4o-mini"
    summary.processing_time_seconds = 3.5
    summary.delivered = False
    summary.delivered_at = None
    return summary


def _make_action_items(meeting_id: uuid.UUID, count: int = 2):
    """Create mock ActionItem objects."""
    items = []
    for i in range(count):
        item = MagicMock()
        item.id = uuid.uuid4()
        item.meeting_id = meeting_id
        item.description = f"Action item {i + 1}"
        item.assigned_to_name = "Bob Williams" if i == 0 else "Alice Johnson"
        item.assigned_to_user_id = f"aad-user-{i + 1:03d}"
        item.assigned_to_email = f"user{i + 1}@contoso.com"
        item.deadline = datetime.now(timezone.utc) + timedelta(days=i + 1)
        item.priority = "high" if i == 0 else "medium"
        item.status = "pending"
        item.nudge_count = 0
        item.last_nudged_at = None
        item.meeting = _make_meeting()  # for send_nudge to access meeting subject
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Test: deliver_summary posts card
# ---------------------------------------------------------------------------

async def test_deliver_summary_posts_card():
    """deliver_summary should call post_to_meeting_chat with the summary card."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from meeting_service.services.delivery import DeliveryService

        settings = Settings()
        mock_graph = AsyncMock()
        mock_graph.post_to_meeting_chat = AsyncMock(return_value={"id": "msg-001"})

        service = DeliveryService(graph_client=mock_graph, settings=settings)

        meeting = _make_meeting()
        summary = _make_summary(meeting.id)
        action_items = _make_action_items(meeting.id)

        await service.deliver_summary(meeting, summary, action_items)

        # Verify that post_to_meeting_chat was called
        mock_graph.post_to_meeting_chat.assert_called_once()
        call_args = mock_graph.post_to_meeting_chat.call_args

        # First arg should be the thread_id
        assert call_args[0][0] == "19:meeting_test@thread.v2"
        # Second arg should be a dict (the Adaptive Card)
        assert isinstance(call_args[0][1], dict)


# ---------------------------------------------------------------------------
# Test: deliver_summary marks as delivered
# ---------------------------------------------------------------------------

async def test_deliver_summary_marks_as_delivered():
    """deliver_summary should set delivered=True and delivered_at timestamp."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from meeting_service.services.delivery import DeliveryService

        settings = Settings()
        mock_graph = AsyncMock()
        mock_graph.post_to_meeting_chat = AsyncMock(return_value={"id": "msg-001"})

        service = DeliveryService(graph_client=mock_graph, settings=settings)

        meeting = _make_meeting()
        summary = _make_summary(meeting.id)
        action_items = _make_action_items(meeting.id)

        assert summary.delivered is False
        assert summary.delivered_at is None

        before = datetime.now(timezone.utc)
        await service.deliver_summary(meeting, summary, action_items)
        after = datetime.now(timezone.utc)

        assert summary.delivered is True
        assert summary.delivered_at is not None
        # The delivered_at timestamp should be recent
        assert before <= summary.delivered_at <= after


# ---------------------------------------------------------------------------
# Test: send_nudge updates tracking
# ---------------------------------------------------------------------------

async def test_send_nudge_updates_tracking():
    """send_nudge should increment nudge_count and set last_nudged_at."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from meeting_service.config import Settings
        from meeting_service.services.delivery import DeliveryService

        settings = Settings()
        mock_graph = AsyncMock()
        mock_graph.send_proactive_message = AsyncMock(
            return_value={"id": "msg-nudge-001"}
        )

        service = DeliveryService(graph_client=mock_graph, settings=settings)

        meeting = _make_meeting()
        action_items = _make_action_items(meeting.id, count=1)
        item = action_items[0]
        item.nudge_count = 0
        item.last_nudged_at = None

        before = datetime.now(timezone.utc)
        await service.send_nudge(item)
        after = datetime.now(timezone.utc)

        # Verify nudge tracking was updated
        assert item.nudge_count == 1
        assert item.last_nudged_at is not None
        assert before <= item.last_nudged_at <= after

        # Verify proactive message was sent to the correct user
        mock_graph.send_proactive_message.assert_called_once()
        call_args = mock_graph.send_proactive_message.call_args
        assert call_args[0][0] == item.assigned_to_user_id
