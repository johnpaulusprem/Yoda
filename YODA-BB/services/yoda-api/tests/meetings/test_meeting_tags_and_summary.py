"""Tests for Feature 5.1 (Meeting Tags) and Feature 5.2 (Edit Summary).

Covers:
- compute_tags unit tests for all tag conditions
- GET /api/meetings returns MeetingWithTagsResponse items with computed tags
- PATCH /api/meetings/{meeting_id}/summary partial update
- PATCH /api/meetings/{meeting_id}/summary 404 cases
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import _TEST_ENV

pytestmark = pytest.mark.asyncio


# ===================================================================
# Feature 5.1 — compute_tags unit tests
# ===================================================================


class TestComputeTags:
    """Unit tests for meeting_tag_service.compute_tags."""

    def _make_meeting(self, **overrides):
        m = MagicMock()
        m.status = overrides.get("status", "scheduled")
        m.subject = overrides.get("subject", "Project Kickoff")
        m.organizer_email = overrides.get("organizer_email", "alice@contoso.com")
        m.participants = overrides.get("participants", [])
        return m

    def _make_action_item(self, priority="medium"):
        ai = MagicMock()
        ai.priority = priority
        return ai

    def _make_summary(self, unresolved_questions=None):
        s = MagicMock()
        s.unresolved_questions = unresolved_questions or []
        return s

    def _make_participant(self, email):
        p = MagicMock()
        p.email = email
        return p

    def test_empty_meeting_no_tags(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting()
            tags = compute_tags(m)
            assert tags == []

    def test_brief_ready_tag(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting()
            tags = compute_tags(m, has_brief=True)
            assert "Brief Ready" in tags

    def test_has_actions_tag(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting()
            ai = self._make_action_item(priority="medium")
            tags = compute_tags(m, action_items=[ai])
            assert "Has Actions" in tags
            assert "High Priority" not in tags

    def test_high_priority_tag(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting()
            ai = self._make_action_item(priority="high")
            tags = compute_tags(m, action_items=[ai])
            assert "Has Actions" in tags
            assert "High Priority" in tags

    def test_recurring_tag_standup(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting(subject="Daily Standup")
            tags = compute_tags(m)
            assert "Recurring" in tags

    def test_recurring_tag_weekly_sync(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting(subject="Team Weekly Sync")
            tags = compute_tags(m)
            assert "Recurring" in tags

    def test_recurring_tag_not_triggered(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting(subject="Project Kickoff")
            tags = compute_tags(m)
            assert "Recurring" not in tags

    def test_external_tag(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting(
                organizer_email="alice@contoso.com",
                participants=[
                    self._make_participant("bob@contoso.com"),
                    self._make_participant("vendor@external.com"),
                ],
            )
            tags = compute_tags(m)
            assert "External" in tags

    def test_no_external_tag_same_domain(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting(
                organizer_email="alice@contoso.com",
                participants=[
                    self._make_participant("bob@contoso.com"),
                ],
            )
            tags = compute_tags(m)
            assert "External" not in tags

    def test_decision_needed_tag(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting()
            s = self._make_summary(unresolved_questions=["Who owns the rollout?"])
            tags = compute_tags(m, summary=s)
            assert "Decision Needed" in tags

    def test_in_progress_tag(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting(status="in_progress")
            tags = compute_tags(m)
            assert "In Progress" in tags

    def test_completed_tag_with_summary(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting(status="completed")
            s = self._make_summary()
            tags = compute_tags(m, summary=s)
            assert "Completed" in tags

    def test_completed_without_summary_no_tag(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting(status="completed")
            tags = compute_tags(m)
            assert "Completed" not in tags

    def test_tags_are_sorted(self):
        with patch.dict("os.environ", _TEST_ENV, clear=False):
            from meeting_service.services.meeting_tag_service import compute_tags

            m = self._make_meeting(status="in_progress", subject="Daily Standup")
            ai = self._make_action_item(priority="high")
            tags = compute_tags(m, action_items=[ai], has_brief=True)
            assert tags == sorted(tags)


# ===================================================================
# Feature 5.1 — Integration: GET /api/meetings returns tags
# ===================================================================


async def test_list_meetings_returns_tags(async_session: AsyncSession, test_client):
    """GET /api/meetings should return MeetingWithTagsResponse with computed tags."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from yoda_foundation.models.meeting import Meeting
        from yoda_foundation.models.action_item import ActionItem
        from yoda_foundation.models.summary import MeetingSummary

        now = datetime.now(timezone.utc)
        meeting_id = uuid.uuid4()

        meeting = Meeting(
            id=meeting_id,
            teams_meeting_id="teams-tag-test-001",
            thread_id="19:meeting_tags@thread.v2",
            join_url="https://teams.microsoft.com/l/meetup-join/tag-test",
            subject="Weekly Sync",
            organizer_id="aad-user-001",
            organizer_name="Alice Johnson",
            organizer_email="alice@contoso.com",
            scheduled_start=now - timedelta(hours=2),
            scheduled_end=now - timedelta(hours=1),
            status="completed",
            participant_count=2,
        )
        async_session.add(meeting)
        await async_session.flush()

        # Add a high-priority action item
        ai = ActionItem(
            meeting_id=meeting_id,
            description="Fix the auth flow",
            assigned_to_name="Bob",
            priority="high",
            status="pending",
        )
        async_session.add(ai)

        # Add a summary with unresolved questions
        summary = MeetingSummary(
            meeting_id=meeting_id,
            summary_text="Discussed sync topics.",
            decisions=[],
            key_topics=[],
            unresolved_questions=["Who handles staging?"],
            model_used="gpt-4o-mini",
            processing_time_seconds=1.5,
            delivered=False,
        )
        async_session.add(summary)
        await async_session.commit()

        resp = await test_client.get("/api/meetings")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total"] >= 1

        # Find our meeting in the response
        tagged_meeting = None
        for item in data["items"]:
            if item["id"] == str(meeting_id):
                tagged_meeting = item
                break

        assert tagged_meeting is not None, "Test meeting not found in response"
        tags = tagged_meeting["tags"]
        assert "Has Actions" in tags
        assert "High Priority" in tags
        assert "Recurring" in tags  # "Weekly Sync" matches recurring pattern
        assert "Decision Needed" in tags  # unresolved_questions present
        assert "Completed" in tags  # status=completed + summary present


async def test_list_meetings_empty_tags_for_simple_meeting(test_client):
    """A meeting with no actions, no summary should have minimal tags."""
    resp = await test_client.get("/api/meetings")
    assert resp.status_code == 200
    data = resp.json()
    # All items should have a 'tags' key (even if empty list)
    for item in data["items"]:
        assert "tags" in item
        assert isinstance(item["tags"], list)


# ===================================================================
# Feature 5.2 — PATCH /api/meetings/{meeting_id}/summary
# ===================================================================


@pytest_asyncio.fixture
async def meeting_with_summary(async_session: AsyncSession):
    """Create a meeting with a summary for edit tests."""
    from yoda_foundation.models.meeting import Meeting
    from yoda_foundation.models.summary import MeetingSummary

    now = datetime.now(timezone.utc)
    meeting_id = uuid.uuid4()

    meeting = Meeting(
        id=meeting_id,
        teams_meeting_id="teams-summary-edit-001",
        thread_id="19:meeting_edit@thread.v2",
        join_url="https://teams.microsoft.com/l/meetup-join/edit-test",
        subject="Summary Edit Test",
        organizer_id="aad-user-001",
        organizer_name="Alice Johnson",
        organizer_email="alice@contoso.com",
        scheduled_start=now - timedelta(hours=2),
        scheduled_end=now - timedelta(hours=1),
        status="completed",
        participant_count=2,
    )
    async_session.add(meeting)
    await async_session.flush()

    summary = MeetingSummary(
        meeting_id=meeting_id,
        summary_text="Original summary text.",
        decisions=[{"description": "Use REST API", "made_by": "Alice"}],
        key_topics=[{"topic": "API Design"}],
        unresolved_questions=["Who handles deployment?"],
        model_used="gpt-4o-mini",
        processing_time_seconds=2.5,
        delivered=False,
    )
    async_session.add(summary)
    await async_session.commit()
    await async_session.refresh(meeting)
    await async_session.refresh(summary)

    return meeting, summary


async def test_edit_summary_partial_update(
    async_session: AsyncSession,
    test_client,
    meeting_with_summary,
):
    """PATCH should update only provided fields and return full summary."""
    meeting, summary = meeting_with_summary

    resp = await test_client.patch(
        f"/api/meetings/{meeting.id}/summary",
        json={"summary_text": "Updated summary text."},
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["summary_text"] == "Updated summary text."
    # Other fields should be unchanged
    assert data["decisions"] == [{"description": "Use REST API", "made_by": "Alice"}]
    assert data["unresolved_questions"] == ["Who handles deployment?"]
    assert data["meeting_id"] == str(meeting.id)


async def test_edit_summary_update_multiple_fields(
    async_session: AsyncSession,
    test_client,
    meeting_with_summary,
):
    """PATCH with multiple fields should update all of them."""
    meeting, summary = meeting_with_summary

    resp = await test_client.patch(
        f"/api/meetings/{meeting.id}/summary",
        json={
            "summary_text": "New summary.",
            "decisions": [{"description": "Migrate to GraphQL", "made_by": "Bob"}],
            "unresolved_questions": [],
        },
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["summary_text"] == "New summary."
    assert data["decisions"] == [{"description": "Migrate to GraphQL", "made_by": "Bob"}]
    assert data["unresolved_questions"] == []


async def test_edit_summary_meeting_not_found(test_client):
    """PATCH on a non-existent meeting should return 404."""
    fake_id = uuid.uuid4()
    resp = await test_client.patch(
        f"/api/meetings/{fake_id}/summary",
        json={"summary_text": "Doesn't matter."},
    )
    assert resp.status_code == 404
    assert "Meeting not found" in resp.json()["detail"]


async def test_edit_summary_no_summary_found(
    async_session: AsyncSession,
    test_client,
    sample_meeting,
):
    """PATCH on a meeting with no summary should return 404."""
    resp = await test_client.patch(
        f"/api/meetings/{sample_meeting.id}/summary",
        json={"summary_text": "No summary to edit."},
    )
    assert resp.status_code == 404
    assert "Summary not found" in resp.json()["detail"]


async def test_edit_summary_empty_body(
    test_client,
    meeting_with_summary,
):
    """PATCH with no fields should return 400."""
    meeting, _ = meeting_with_summary
    resp = await test_client.patch(
        f"/api/meetings/{meeting.id}/summary",
        json={},
    )
    assert resp.status_code == 400
    assert "No fields to update" in resp.json()["detail"]
