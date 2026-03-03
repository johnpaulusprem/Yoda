"""Analytics and insights service."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cxo_ai_companion.models import Meeting, ActionItem, MeetingInsight, MeetingSummary, MeetingParticipant

logger = logging.getLogger(__name__)


class InsightService:
    """Generates analytics and insights for executives.

    Provides meeting time analysis, action item completion stats,
    collaboration pattern detection, decision conflict analysis,
    and recurring topic identification.

    Args:
        ai_connector: Azure AI Foundry client for AI-powered conflict detection.
        db_session_factory: Async session factory for querying meeting data.
    """

    def __init__(self, ai_connector, db_session_factory) -> None:
        self._ai = ai_connector
        self._session_factory = db_session_factory

    async def get_meeting_time_analysis(self, user_id: str, days: int = 30) -> dict:
        """Analyze meeting time usage over a given period.

        Args:
            user_id: Azure AD user ID of the executive.
            days: Look-back window in days.

        Returns:
            Dict with total_meetings, total_hours, avg_per_week, and
            avg_duration_minutes.
        """
        async with self._session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            result = await db.execute(
                select(Meeting).where(
                    Meeting.status == "completed",
                    Meeting.scheduled_start >= cutoff,
                )
            )
            meetings = result.scalars().all()
            total_minutes = sum(
                ((m.actual_end or m.scheduled_end) - (m.actual_start or m.scheduled_start)).total_seconds() / 60
                for m in meetings
            )
            return {
                "total_meetings": len(meetings),
                "total_hours": round(total_minutes / 60, 1),
                "avg_per_week": round(len(meetings) / max(days / 7, 1), 1),
                "avg_duration_minutes": round(total_minutes / max(len(meetings), 1), 0),
            }

    async def get_action_completion_stats(self, user_id: str, days: int = 30) -> dict:
        """Compute action item completion statistics.

        Args:
            user_id: Azure AD user ID of the executive.
            days: Look-back window in days.

        Returns:
            Dict with total, completed, and rate (percentage) fields.
        """
        async with self._session_factory() as db:
            total_r = await db.execute(select(func.count()).select_from(ActionItem))
            completed_r = await db.execute(
                select(func.count()).select_from(ActionItem).where(ActionItem.status == "completed")
            )
            total = total_r.scalar_one()
            completed = completed_r.scalar_one()
            return {
                "total": total,
                "completed": completed,
                "rate": round(completed / max(total, 1) * 100, 1),
            }

    async def detect_conflicts(self, meeting_id: UUID) -> list[dict]:
        """Compare new decisions against past decisions for contradictions.

        Uses GPT-4o-mini to identify conflicts between the current meeting's
        decisions and those from the last 20 past meetings.

        Args:
            meeting_id: UUID of the meeting whose decisions to analyze.

        Returns:
            List of conflict dicts with current_decision, past_decision,
            conflict_type, and severity fields.
        """
        async with self._session_factory() as db:
            current = await db.execute(
                select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id)
            )
            current_summary = current.scalar_one_or_none()
            if not current_summary or not current_summary.decisions:
                return []

            past = await db.execute(
                select(MeetingSummary)
                .where(MeetingSummary.meeting_id != meeting_id)
                .order_by(MeetingSummary.created_at.desc())
                .limit(20)
            )
            past_summaries = past.scalars().all()

            past_decisions = []
            for ps in past_summaries:
                for d in ps.decisions or []:
                    past_decisions.append({
                        "decision": d.get("decision", ""),
                        "meeting_id": str(ps.meeting_id),
                        "date": str(ps.created_at),
                    })

            if not past_decisions:
                return []

            from azure.ai.inference.models import SystemMessage, UserMessage

            prompt = (
                f"Current decisions: {current_summary.decisions}\n\n"
                f"Past decisions: {past_decisions[:20]}\n\n"
                "Identify any contradictions. Return JSON array of conflicts "
                "with fields: current_decision, past_decision, conflict_type, severity."
            )
            try:
                response = await self._ai.complete(
                    model="gpt-4o-mini",
                    messages=[
                        SystemMessage(content="You are a decision conflict detector. Return valid JSON only."),
                        UserMessage(content=prompt),
                    ],
                )
                import json

                return json.loads(response) if response.strip().startswith("[") else []
            except Exception:
                logger.warning("Conflict detection failed for meeting %s", meeting_id)
                return []

    async def get_collaboration_analysis(self, user_id: str, days: int = 30) -> dict:
        """Analyze collaboration patterns: top collaborators and stale contacts.

        Identifies the most frequently co-attended participants and flags
        contacts not met in over 14 days.

        Args:
            user_id: Azure AD user ID of the executive.
            days: Look-back window in days.

        Returns:
            Dict with top_collaborators, stale_contacts, and period_days.
        """
        async with self._session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=days)

            # Count interactions per person
            result = await db.execute(
                select(MeetingParticipant.user_id, MeetingParticipant.display_name, func.count().label("count"))
                .join(Meeting, MeetingParticipant.meeting_id == Meeting.id)
                .where(
                    Meeting.scheduled_start >= cutoff,
                    MeetingParticipant.user_id.isnot(None),
                )
                .group_by(MeetingParticipant.user_id, MeetingParticipant.display_name)
                .order_by(func.count().desc())
                .limit(20)
            )
            top_collaborators = [
                {"user_id": row.user_id, "display_name": row.display_name, "interaction_count": row.count}
                for row in result.all()
            ]

            # Detect stale 1:1s -- people not met in >14 days who were previously met
            fourteen_days_ago = datetime.now(UTC) - timedelta(days=14)
            all_contacts_result = await db.execute(
                select(
                    MeetingParticipant.user_id,
                    MeetingParticipant.display_name,
                    func.max(Meeting.scheduled_start).label("last_meeting"),
                )
                .join(Meeting, MeetingParticipant.meeting_id == Meeting.id)
                .where(
                    MeetingParticipant.user_id.isnot(None),
                    Meeting.status == "completed",
                )
                .group_by(MeetingParticipant.user_id, MeetingParticipant.display_name)
            )
            stale_contacts = []
            for row in all_contacts_result.all():
                if row.last_meeting < fourteen_days_ago:
                    stale_contacts.append({
                        "user_id": row.user_id,
                        "display_name": row.display_name,
                        "last_meeting": str(row.last_meeting),
                        "days_since": (datetime.now(UTC) - row.last_meeting).days,
                    })

            return {
                "top_collaborators": top_collaborators,
                "stale_contacts": stale_contacts[:10],
                "period_days": days,
            }

    async def get_pattern_analysis(self, user_id: str, days: int = 30) -> dict:
        """Detect recurring topics and potential decision reversals over a period.

        Counts topic frequency across meeting summaries and flags decisions
        that appear to contradict earlier ones on the same subject.

        Args:
            user_id: Azure AD user ID of the executive.
            days: Look-back window in days.

        Returns:
            Dict with recurring_topics, potential_reversals, period_days,
            and summaries_analyzed.
        """
        async with self._session_factory() as db:
            cutoff = datetime.now(UTC) - timedelta(days=days)

            # Get summaries in the period
            result = await db.execute(
                select(MeetingSummary)
                .join(Meeting, MeetingSummary.meeting_id == Meeting.id)
                .where(Meeting.scheduled_start >= cutoff)
                .order_by(Meeting.scheduled_start.desc())
            )
            summaries = result.scalars().all()

            # Count recurring topics
            topic_counter: Counter[str] = Counter()
            for s in summaries:
                for topic in s.key_topics or []:
                    topic_name = topic.get("topic", "") if isinstance(topic, dict) else str(topic)
                    if topic_name:
                        topic_counter[topic_name.lower().strip()] += 1

            recurring_topics = [
                {"topic": topic, "count": count}
                for topic, count in topic_counter.most_common(10)
                if count >= 2
            ]

            # Detect potential decision reversals (same topic decided differently)
            decisions_by_topic: defaultdict[str, list[dict]] = defaultdict(list)
            for s in summaries:
                for d in s.decisions or []:
                    dec_text = d.get("decision", "") if isinstance(d, dict) else str(d)
                    if dec_text:
                        # Use first few significant words as topic key
                        words = [w.lower() for w in dec_text.split()[:5] if len(w) > 3]
                        topic_key = " ".join(words)
                        if topic_key:
                            decisions_by_topic[topic_key].append({
                                "decision": dec_text,
                                "meeting_id": str(s.meeting_id),
                                "date": str(s.created_at),
                            })

            potential_reversals = [
                {"topic_key": key, "decisions": decs}
                for key, decs in decisions_by_topic.items()
                if len(decs) >= 2
            ][:5]

            return {
                "recurring_topics": recurring_topics,
                "potential_reversals": potential_reversals,
                "period_days": days,
                "summaries_analyzed": len(summaries),
            }
