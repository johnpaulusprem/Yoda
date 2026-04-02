"""Recurring topic detection across meeting summaries."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_foundation.models.summary import MeetingSummary

logger = logging.getLogger(__name__)


class RecurringTopicService:
    """Analyzes key_topics from MeetingSummary to find recurring themes."""

    async def detect_recurring_topics(
        self, db: AsyncSession, days: int = 30
    ) -> list[dict]:
        """Find topics mentioned in 3+ meetings within the period.

        Args:
            db: Async SQLAlchemy session.
            days: Look-back window in days.

        Returns:
            List of dicts with topic, meeting_count, and occurrences,
            sorted by meeting_count descending.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await db.execute(
            select(MeetingSummary).where(MeetingSummary.created_at >= cutoff)
        )
        summaries = result.scalars().all()

        topic_counts: dict[str, list[dict]] = {}
        for summary in summaries:
            for topic in summary.key_topics or []:
                name = topic.get("topic", "").lower().strip() if isinstance(topic, dict) else str(topic).lower().strip()
                if name:
                    topic_counts.setdefault(name, []).append({
                        "meeting_id": str(summary.meeting_id),
                        "detail": topic.get("detail", "") if isinstance(topic, dict) else "",
                    })

        recurring: list[dict] = []
        for topic_name, occurrences in topic_counts.items():
            unique_meetings = set(o["meeting_id"] for o in occurrences)
            if len(unique_meetings) >= 3:
                recurring.append({
                    "topic": topic_name,
                    "meeting_count": len(unique_meetings),
                    "occurrences": occurrences[:5],
                })

        return sorted(recurring, key=lambda x: x["meeting_count"], reverse=True)
