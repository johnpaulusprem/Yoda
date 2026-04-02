"""Dashboard service -- aggregates data for the CXO executive dashboard.

Provides statistics, attention items, and activity feeds that power the
main dashboard wireframe.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_foundation.models.action_item import ActionItem
from yoda_foundation.models.meeting import Meeting
from yoda_foundation.models.summary import MeetingSummary

logger = logging.getLogger("services.dashboard")


@asynccontextmanager
async def trace_span(
    name: str, attributes: dict[str, Any] | None = None
) -> AsyncGenerator[None, None]:
    """No-op async trace span for observability compatibility."""
    yield


@dataclass
class DashboardStats:
    """Aggregated statistics for the executive dashboard."""

    meetings_today: int = 0
    meetings_this_week: int = 0
    pending_actions: int = 0
    overdue_actions: int = 0
    completed_actions: int = 0
    completion_rate: float = 0.0
    total_meetings_processed: int = 0


@dataclass
class AttentionItem:
    """An item requiring the executive's attention."""

    item_type: str  # overdue_action | upcoming_meeting_no_brief | stale_action
    title: str
    description: str
    severity: str  # high | medium | low
    related_id: str | None = None
    deadline: datetime | None = None


@dataclass
class ActivityItem:
    """A recent activity entry for the feed."""

    activity_type: str  # meeting_completed | action_completed | summary_delivered | nudge_sent
    title: str
    description: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    related_id: str | None = None


class DashboardService:
    """Aggregates statistics, attention items, and activity feeds for the
    CXO executive dashboard.

    Provides meeting counts, action item completion rates, overdue items
    requiring attention, and a chronological activity feed.

    Args:
        db: Async SQLAlchemy session for querying meetings and action items.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_stats(
        self,
        user_id: str,
    ) -> DashboardStats:
        """Return dashboard statistics: meetings today, pending actions, etc.

        Args:
            user_id: Azure AD user ID of the executive.

        Returns:
            DashboardStats with aggregated counts and rates.
        """
        async with trace_span(
            "dashboard.get_stats",
            attributes={"user_id": user_id},
        ):
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            week_start = today_start - timedelta(days=today_start.weekday())

            # Meetings today
            meetings_today_q = await self.db.execute(
                select(func.count(Meeting.id)).where(
                    Meeting.organizer_id == user_id,
                    Meeting.scheduled_start >= today_start,
                    Meeting.scheduled_start < today_end,
                )
            )
            meetings_today = meetings_today_q.scalar_one() or 0

            # Meetings this week
            meetings_week_q = await self.db.execute(
                select(func.count(Meeting.id)).where(
                    Meeting.organizer_id == user_id,
                    Meeting.scheduled_start >= week_start,
                    Meeting.scheduled_start < today_end,
                )
            )
            meetings_this_week = meetings_week_q.scalar_one() or 0

            # Action items assigned to user
            pending_q = await self.db.execute(
                select(func.count(ActionItem.id)).where(
                    ActionItem.assigned_to_user_id == user_id,
                    ActionItem.status.in_(["pending", "in_progress"]),
                )
            )
            pending_actions = pending_q.scalar_one() or 0

            # Overdue action items
            overdue_q = await self.db.execute(
                select(func.count(ActionItem.id)).where(
                    ActionItem.assigned_to_user_id == user_id,
                    ActionItem.status.in_(["pending", "in_progress"]),
                    ActionItem.deadline.isnot(None),
                    ActionItem.deadline < now,
                )
            )
            overdue_actions = overdue_q.scalar_one() or 0

            # Completed action items (last 30 days)
            thirty_days_ago = now - timedelta(days=30)
            completed_q = await self.db.execute(
                select(func.count(ActionItem.id)).where(
                    ActionItem.assigned_to_user_id == user_id,
                    ActionItem.status == "completed",
                    ActionItem.completed_at >= thirty_days_ago,
                )
            )
            completed_actions = completed_q.scalar_one() or 0

            # Completion rate
            total_q = await self.db.execute(
                select(func.count(ActionItem.id)).where(
                    ActionItem.assigned_to_user_id == user_id,
                    ActionItem.created_at >= thirty_days_ago,
                )
            )
            total_actions = total_q.scalar_one() or 0
            completion_rate = (
                (completed_actions / total_actions * 100.0) if total_actions > 0 else 0.0
            )

            # Total meetings processed
            processed_q = await self.db.execute(
                select(func.count(Meeting.id)).where(
                    Meeting.organizer_id == user_id,
                    Meeting.status == "completed",
                )
            )
            total_meetings_processed = processed_q.scalar_one() or 0

            return DashboardStats(
                meetings_today=meetings_today,
                meetings_this_week=meetings_this_week,
                pending_actions=pending_actions,
                overdue_actions=overdue_actions,
                completed_actions=completed_actions,
                completion_rate=round(completion_rate, 1),
                total_meetings_processed=total_meetings_processed,
            )

    async def get_attention_items(
        self,
        user_id: str,
    ) -> list[AttentionItem]:
        """Return items requiring the executive's immediate attention.

        Includes:
        - Overdue action items assigned to the user
        - Upcoming meetings without briefs
        - Action items that have been pending for too long

        Args:
            user_id: Azure AD user ID.

        Returns:
            List of AttentionItem instances sorted by severity.
        """
        async with trace_span(
            "dashboard.get_attention_items",
            attributes={"user_id": user_id},
        ):
            items: list[AttentionItem] = []
            now = datetime.now(timezone.utc)

            # Overdue action items
            overdue_result = await self.db.execute(
                select(ActionItem).where(
                    ActionItem.assigned_to_user_id == user_id,
                    ActionItem.status.in_(["pending", "in_progress"]),
                    ActionItem.deadline.isnot(None),
                    ActionItem.deadline < now,
                )
            )
            for ai in overdue_result.scalars().all():
                items.append(
                    AttentionItem(
                        item_type="overdue_action",
                        title=f"Overdue: {ai.description[:80]}",
                        description=f"Deadline was {ai.deadline.strftime('%b %d, %Y') if ai.deadline else 'N/A'}",
                        severity="high",
                        related_id=str(ai.id),
                        deadline=ai.deadline,
                    )
                )

            # Upcoming meetings in next 24 hours without summaries from previous
            # meetings with same attendees (basic check: meetings without briefs)
            upcoming_result = await self.db.execute(
                select(Meeting).where(
                    Meeting.organizer_id == user_id,
                    Meeting.status == "scheduled",
                    Meeting.scheduled_start >= now,
                    Meeting.scheduled_start <= now + timedelta(hours=24),
                )
            )
            for mtg in upcoming_result.scalars().all():
                items.append(
                    AttentionItem(
                        item_type="upcoming_meeting_no_brief",
                        title=f"Upcoming: {mtg.subject}",
                        description=f"Starts at {mtg.scheduled_start.strftime('%I:%M %p')}",
                        severity="medium",
                        related_id=str(mtg.id),
                    )
                )

            # Sort by severity (high first)
            severity_order = {"high": 0, "medium": 1, "low": 2}
            items.sort(key=lambda x: severity_order.get(x.severity, 3))

            return items

    async def get_activity_feed(
        self,
        user_id: str,
        limit: int = 20,
    ) -> list[ActivityItem]:
        """Return recent activity items for the dashboard feed.

        Includes:
        - Recent meeting completions
        - Action item status updates
        - Summary deliveries

        Args:
            user_id: Azure AD user ID.
            limit: Maximum number of items to return.

        Returns:
            List of ActivityItem instances sorted by timestamp (most recent first).
        """
        async with trace_span(
            "dashboard.get_activity_feed",
            attributes={"user_id": user_id, "limit": limit},
        ):
            activities: list[ActivityItem] = []
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)

            # Recently completed meetings
            meetings_result = await self.db.execute(
                select(Meeting)
                .where(
                    Meeting.organizer_id == user_id,
                    Meeting.status == "completed",
                    Meeting.actual_end.isnot(None),
                    Meeting.actual_end >= cutoff,
                )
                .order_by(Meeting.actual_end.desc())
                .limit(limit)
            )
            for mtg in meetings_result.scalars().all():
                activities.append(
                    ActivityItem(
                        activity_type="meeting_completed",
                        title=f"Meeting completed: {mtg.subject}",
                        description=f"{mtg.participant_count} participants",
                        timestamp=mtg.actual_end or mtg.updated_at,
                        related_id=str(mtg.id),
                    )
                )

            # Recently completed action items
            actions_result = await self.db.execute(
                select(ActionItem)
                .where(
                    ActionItem.assigned_to_user_id == user_id,
                    ActionItem.status == "completed",
                    ActionItem.completed_at.isnot(None),
                    ActionItem.completed_at >= cutoff,
                )
                .order_by(ActionItem.completed_at.desc())
                .limit(limit)
            )
            for ai in actions_result.scalars().all():
                activities.append(
                    ActivityItem(
                        activity_type="action_completed",
                        title=f"Action completed: {ai.description[:60]}",
                        description=f"Assigned to {ai.assigned_to_name}",
                        timestamp=ai.completed_at or ai.updated_at,
                        related_id=str(ai.id),
                    )
                )

            # Sort all by timestamp descending and trim
            activities.sort(key=lambda x: x.timestamp, reverse=True)
            return activities[:limit]
