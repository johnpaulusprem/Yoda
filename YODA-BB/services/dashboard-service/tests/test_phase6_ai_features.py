"""Tests for Phase 6 AI features: conflict detection, decision velocity,
recurring topics, decision reversals, and recommendations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dashboard_service.services.conflict_detection_service import ConflictDetectionService
from dashboard_service.services.topic_detection_service import RecurringTopicService


# ---------------------------------------------------------------------------
# Shared engine / session fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def p6_engine():
    """In-memory SQLite engine for Phase 6 tests."""
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
async def p6_session(p6_engine) -> AsyncSession:
    """Yield an async session for Phase 6 tests."""
    factory = async_sessionmaker(p6_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Helper: seed meetings and summaries
# ---------------------------------------------------------------------------

async def _seed_meeting_with_summary(
    session: AsyncSession,
    *,
    subject: str = "Sprint Planning",
    decisions: list[dict] | None = None,
    key_topics: list[dict] | None = None,
    days_ago: int = 5,
) -> tuple:
    """Create a meeting and its summary, returning (meeting, summary)."""
    from yoda_foundation.models.meeting import Meeting
    from yoda_foundation.models.summary import MeetingSummary

    now = datetime.now(timezone.utc)
    meeting_id = uuid.uuid4()
    meeting = Meeting(
        id=meeting_id,
        teams_meeting_id=f"teams-{meeting_id}",
        join_url=f"https://teams.microsoft.com/l/meetup-join/{meeting_id}",
        subject=subject,
        organizer_id="test-user-001",
        organizer_name="Alice Johnson",
        organizer_email="alice@contoso.com",
        scheduled_start=now - timedelta(days=days_ago, hours=2),
        scheduled_end=now - timedelta(days=days_ago, hours=1),
        actual_start=now - timedelta(days=days_ago, hours=2),
        actual_end=now - timedelta(days=days_ago, hours=1),
        status="completed",
        participant_count=3,
    )
    session.add(meeting)

    summary = MeetingSummary(
        id=uuid.uuid4(),
        meeting_id=meeting_id,
        summary_text="Test meeting summary.",
        decisions=decisions or [],
        key_topics=key_topics or [],
        model_used="gpt-4o-mini",
        processing_time_seconds=2.5,
    )
    session.add(summary)
    await session.commit()
    await session.refresh(meeting)
    await session.refresh(summary)
    return meeting, summary


# ===========================================================================
# 6.1: Conflict Detection Service
# ===========================================================================

class TestConflictDetectionService:
    """Tests for ConflictDetectionService.check_for_conflicts."""

    @pytest.mark.asyncio
    async def test_no_conflicts_when_no_past_summaries(self, p6_session):
        svc = ConflictDetectionService()
        conflicts = await svc.check_for_conflicts(
            p6_session, str(uuid.uuid4()), [{"decision": "Increase the marketing budget for Q3"}]
        )
        assert conflicts == []

    @pytest.mark.asyncio
    async def test_detects_contradiction(self, p6_session):
        """A new decision to 'increase budget' should conflict with a past 'decrease budget'."""
        past_meeting, _ = await _seed_meeting_with_summary(
            p6_session,
            decisions=[{"decision": "Decrease the marketing budget for Q3 project allocation"}],
            days_ago=10,
        )

        new_meeting_id = str(uuid.uuid4())
        new_decisions = [
            {"decision": "Increase the marketing budget for Q3 project allocation"},
        ]

        svc = ConflictDetectionService()
        conflicts = await svc.check_for_conflicts(p6_session, new_meeting_id, new_decisions)

        assert len(conflicts) >= 1
        assert "increase" in conflicts[0]["similarity_reason"].lower() or \
               "decrease" in conflicts[0]["similarity_reason"].lower()

    @pytest.mark.asyncio
    async def test_no_conflict_for_unrelated_decisions(self, p6_session):
        """Unrelated decisions should not trigger a conflict."""
        await _seed_meeting_with_summary(
            p6_session,
            decisions=[{"decision": "Approve the new logo design for branding"}],
            days_ago=10,
        )

        svc = ConflictDetectionService()
        conflicts = await svc.check_for_conflicts(
            p6_session,
            str(uuid.uuid4()),
            [{"decision": "Hire three new engineers for the backend team"}],
        )
        assert conflicts == []

    @pytest.mark.asyncio
    async def test_stores_insights_on_conflict(self, p6_session):
        """Detected conflicts should be stored as MeetingInsight rows."""
        from yoda_foundation.models.insight import MeetingInsight
        from sqlalchemy import select

        await _seed_meeting_with_summary(
            p6_session,
            decisions=[{"decision": "Reject the vendor proposal for cloud migration services"}],
            days_ago=10,
        )

        new_meeting, _ = await _seed_meeting_with_summary(
            p6_session,
            decisions=[{"decision": "Approve the vendor proposal for cloud migration services"}],
            days_ago=1,
        )

        svc = ConflictDetectionService()
        conflicts = await svc.check_for_conflicts(
            p6_session, str(new_meeting.id),
            [{"decision": "Approve the vendor proposal for cloud migration services"}],
        )

        # Verify insights were stored
        result = await p6_session.execute(
            select(MeetingInsight).where(
                MeetingInsight.meeting_id == new_meeting.id,
                MeetingInsight.insight_type == "conflict_detection",
            )
        )
        insights = result.scalars().all()
        assert len(insights) == len(conflicts)


# ===========================================================================
# 6.4: Decision Reversal Detection
# ===========================================================================

class TestDecisionReversalDetection:
    """Tests for ConflictDetectionService.check_reversals_in_series."""

    @pytest.mark.asyncio
    async def test_no_reversals_when_no_past_meetings(self, p6_session):
        meeting, _ = await _seed_meeting_with_summary(
            p6_session,
            subject="Weekly Standup",
            decisions=[{"decision": "Start the migration project next quarter"}],
            days_ago=1,
        )

        svc = ConflictDetectionService()
        reversals = await svc.check_reversals_in_series(
            p6_session, str(meeting.id), "Weekly Standup"
        )
        assert reversals == []

    @pytest.mark.asyncio
    async def test_detects_reversal_in_series(self, p6_session):
        """Two meetings with same subject where decisions contradict."""
        past_meeting, _ = await _seed_meeting_with_summary(
            p6_session,
            subject="Budget Review",
            decisions=[{"decision": "Expand the engineering team budget allocation"}],
            days_ago=14,
        )

        current_meeting, _ = await _seed_meeting_with_summary(
            p6_session,
            subject="Budget Review",
            decisions=[{"decision": "Reduce the engineering team budget allocation"}],
            days_ago=1,
        )

        svc = ConflictDetectionService()
        reversals = await svc.check_reversals_in_series(
            p6_session, str(current_meeting.id), "Budget Review"
        )

        assert len(reversals) >= 1
        assert "expand" in reversals[0]["reason"].lower() or \
               "reduce" in reversals[0]["reason"].lower()

    @pytest.mark.asyncio
    async def test_no_reversal_for_different_subjects(self, p6_session):
        """Meetings with different subjects should not cross-compare."""
        await _seed_meeting_with_summary(
            p6_session,
            subject="Budget Review",
            decisions=[{"decision": "Expand the engineering team budget"}],
            days_ago=14,
        )

        current_meeting, _ = await _seed_meeting_with_summary(
            p6_session,
            subject="Architecture Review",
            decisions=[{"decision": "Reduce the engineering team budget"}],
            days_ago=1,
        )

        svc = ConflictDetectionService()
        reversals = await svc.check_reversals_in_series(
            p6_session, str(current_meeting.id), "Architecture Review"
        )
        assert reversals == []


# ===========================================================================
# 6.3: Recurring Topic Detection
# ===========================================================================

class TestRecurringTopicService:
    """Tests for RecurringTopicService.detect_recurring_topics."""

    @pytest.mark.asyncio
    async def test_empty_db_returns_no_topics(self, p6_session):
        svc = RecurringTopicService()
        result = await svc.detect_recurring_topics(p6_session, days=30)
        assert result == []

    @pytest.mark.asyncio
    async def test_topic_in_two_meetings_not_recurring(self, p6_session):
        """A topic in only 2 meetings should not be returned (threshold is 3)."""
        await _seed_meeting_with_summary(
            p6_session,
            key_topics=[{"topic": "Cloud Migration", "detail": "AWS vs Azure"}],
            days_ago=5,
        )
        await _seed_meeting_with_summary(
            p6_session,
            key_topics=[{"topic": "Cloud Migration", "detail": "Timeline discussion"}],
            days_ago=3,
        )

        svc = RecurringTopicService()
        result = await svc.detect_recurring_topics(p6_session, days=30)
        assert result == []

    @pytest.mark.asyncio
    async def test_topic_in_three_meetings_is_recurring(self, p6_session):
        """A topic in 3 meetings should be returned."""
        for i in range(3):
            await _seed_meeting_with_summary(
                p6_session,
                key_topics=[{"topic": "Cloud Migration", "detail": f"Discussion {i}"}],
                days_ago=10 - i,
            )

        svc = RecurringTopicService()
        result = await svc.detect_recurring_topics(p6_session, days=30)
        assert len(result) == 1
        assert result[0]["topic"] == "cloud migration"
        assert result[0]["meeting_count"] == 3

    @pytest.mark.asyncio
    async def test_sorted_by_meeting_count(self, p6_session):
        """Topics should be sorted by meeting_count descending."""
        # Topic A in 4 meetings
        for i in range(4):
            await _seed_meeting_with_summary(
                p6_session,
                key_topics=[{"topic": "Topic A", "detail": f"A-{i}"}],
                days_ago=15 - i,
            )
        # Topic B in 3 meetings
        for i in range(3):
            await _seed_meeting_with_summary(
                p6_session,
                key_topics=[{"topic": "Topic B", "detail": f"B-{i}"}],
                days_ago=10 - i,
            )

        svc = RecurringTopicService()
        result = await svc.detect_recurring_topics(p6_session, days=30)
        assert len(result) == 2
        assert result[0]["topic"] == "topic a"
        assert result[1]["topic"] == "topic b"


# ===========================================================================
# 6.2: Decision Velocity (route-level test)
# ===========================================================================

class TestDecisionVelocityEndpoint:
    """Tests for GET /api/insights/decision-velocity."""

    @pytest.mark.asyncio
    async def test_empty_db_returns_zero(self, test_client):
        response = await test_client.get("/api/insights/decision-velocity")
        assert response.status_code == 200
        data = response.json()
        assert data["decision_items_completed"] == 0
        assert data["avg_days_to_completion"] is None

    @pytest.mark.asyncio
    async def test_with_decision_items(self, test_client, async_session, sample_meeting):
        """Completed items with decision keywords should be counted."""
        from yoda_foundation.models.action_item import ActionItem

        now = datetime.now(timezone.utc)
        item = ActionItem(
            id=uuid.uuid4(),
            meeting_id=sample_meeting.id,
            description="Approve the new vendor contract for Q2",
            assigned_to_name="Alice Johnson",
            assigned_to_user_id="test-user-001",
            status="completed",
            completed_at=now - timedelta(days=1),
        )
        async_session.add(item)
        await async_session.commit()

        response = await test_client.get("/api/insights/decision-velocity?days=90")
        assert response.status_code == 200
        data = response.json()
        assert data["decision_items_completed"] >= 1
        assert data["avg_days_to_completion"] is not None


# ===========================================================================
# 6.3: Recurring Topics (route-level test)
# ===========================================================================

class TestRecurringTopicsEndpoint:
    """Tests for GET /api/insights/recurring-topics."""

    @pytest.mark.asyncio
    async def test_empty_db(self, test_client):
        response = await test_client.get("/api/insights/recurring-topics")
        assert response.status_code == 200
        data = response.json()
        assert data["recurring_topics"] == []

    @pytest.mark.asyncio
    async def test_with_recurring_data(self, test_client, async_session):
        """Seed 3 summaries with the same topic and verify it appears."""
        from yoda_foundation.models.meeting import Meeting
        from yoda_foundation.models.summary import MeetingSummary

        now = datetime.now(timezone.utc)
        for i in range(3):
            mid = uuid.uuid4()
            meeting = Meeting(
                id=mid,
                teams_meeting_id=f"teams-recur-{i}",
                join_url=f"https://teams.microsoft.com/l/meetup-join/recur-{i}",
                subject=f"Standup {i}",
                organizer_id="test-user-001",
                organizer_name="Alice",
                organizer_email="alice@contoso.com",
                scheduled_start=now - timedelta(days=10 - i, hours=2),
                scheduled_end=now - timedelta(days=10 - i, hours=1),
                status="completed",
                participant_count=2,
            )
            summary = MeetingSummary(
                id=uuid.uuid4(),
                meeting_id=mid,
                summary_text="Standup notes.",
                key_topics=[{"topic": "Tech Debt", "detail": f"iteration {i}"}],
                decisions=[],
                model_used="gpt-4o-mini",
                processing_time_seconds=1.0,
            )
            async_session.add_all([meeting, summary])

        await async_session.commit()

        response = await test_client.get("/api/insights/recurring-topics?days=30")
        assert response.status_code == 200
        data = response.json()
        assert len(data["recurring_topics"]) >= 1
        assert data["recurring_topics"][0]["topic"] == "tech debt"


# ===========================================================================
# 6.5: Recommendations Endpoint
# ===========================================================================

class TestRecommendationsEndpoint:
    """Tests for GET /api/dashboard/recommendations."""

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty(self, test_client):
        response = await test_client.get("/api/dashboard/recommendations")
        assert response.status_code == 200
        data = response.json()
        assert data["recommendations"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_overdue_cluster_recommendation(self, test_client, async_session, sample_meeting):
        """3+ overdue items for the same person triggers an overdue_cluster recommendation."""
        from yoda_foundation.models.action_item import ActionItem

        now = datetime.now(timezone.utc)
        for i in range(3):
            item = ActionItem(
                id=uuid.uuid4(),
                meeting_id=sample_meeting.id,
                description=f"Overdue task {i} for Bob",
                assigned_to_name="Bob Williams",
                assigned_to_user_id="test-user-002",
                deadline=now - timedelta(days=3),
                status="pending",
            )
            async_session.add(item)
        await async_session.commit()

        response = await test_client.get("/api/dashboard/recommendations")
        assert response.status_code == 200
        data = response.json()
        overdue_recs = [r for r in data["recommendations"] if r["type"] == "overdue_cluster"]
        assert len(overdue_recs) >= 1
        assert "Bob Williams" in overdue_recs[0]["title"]
        assert overdue_recs[0]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_stale_one_on_one_recommendation(self, test_client, async_session):
        """A contact not met in 14+ days triggers a stale_one_on_one recommendation."""
        from yoda_foundation.models.meeting import Meeting, MeetingParticipant

        now = datetime.now(timezone.utc)
        mid = uuid.uuid4()
        meeting = Meeting(
            id=mid,
            teams_meeting_id="teams-stale-001",
            join_url="https://teams.microsoft.com/l/meetup-join/stale",
            subject="Old 1:1",
            organizer_id="test-user-001",
            organizer_name="Alice",
            organizer_email="alice@contoso.com",
            scheduled_start=now - timedelta(days=20),
            scheduled_end=now - timedelta(days=20) + timedelta(hours=1),
            status="completed",
            participant_count=2,
        )
        participant = MeetingParticipant(
            id=uuid.uuid4(),
            meeting_id=mid,
            user_id="test-user-003",
            display_name="Charlie Brown",
            email="charlie@contoso.com",
            role="attendee",
        )
        async_session.add_all([meeting, participant])
        await async_session.commit()

        response = await test_client.get("/api/dashboard/recommendations")
        assert response.status_code == 200
        data = response.json()
        stale_recs = [r for r in data["recommendations"] if r["type"] == "stale_one_on_one"]
        assert len(stale_recs) >= 1
        assert "Charlie Brown" in stale_recs[0]["title"]
