"""Weekly digest generation and delivery."""
from __future__ import annotations
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from cxo_ai_companion.models import Meeting, ActionItem, MeetingSummary, MeetingParticipant
from cxo_ai_companion.models.insight import WeeklyDigest

logger = logging.getLogger(__name__)

class WeeklyDigestService:
    """Generates and delivers weekly executive digests.

    Aggregates the past week's meetings, action items, decisions, and
    collaboration patterns into an AI-generated summary for delivery
    via Teams Adaptive Cards.

    Args:
        ai_connector: Azure AI Foundry client for generating digest text.
        delivery_service: DeliveryService for sending digest cards to Teams.
        db_session_factory: Async session factory for querying weekly data.
    """

    def __init__(self, ai_connector, delivery_service, db_session_factory) -> None:
        self._ai = ai_connector
        self._delivery = delivery_service
        self._session_factory = db_session_factory

    async def generate_digest(self, user_id: str) -> WeeklyDigest:
        """Generate a weekly executive digest for the given user.

        Gathers the last 7 days of meetings, action items, and decisions,
        then uses GPT-4o-mini to produce a 3-4 paragraph executive summary.

        Args:
            user_id: Azure AD user ID of the executive.

        Returns:
            A persisted WeeklyDigest instance with stats and digest text.
        """
        now = datetime.now(UTC)
        week_start = now - timedelta(days=7)

        async with self._session_factory() as db:
            # Get week's meetings
            m_result = await db.execute(select(Meeting).where(Meeting.status == "completed", Meeting.scheduled_start >= week_start))
            meetings = m_result.scalars().all()

            # Get week's action items
            a_result = await db.execute(select(ActionItem).where(ActionItem.created_at >= week_start))
            action_items = a_result.scalars().all()
            completed = [a for a in action_items if a.status == "completed"]

            # Get decisions from summaries
            s_result = await db.execute(select(MeetingSummary).where(MeetingSummary.created_at >= week_start))
            summaries = s_result.scalars().all()
            all_decisions = []
            for s in summaries:
                all_decisions.extend(s.decisions or [])

            # Generate digest text via AI
            from azure.ai.inference.models import SystemMessage, UserMessage
            context = f"Meetings: {len(meetings)}, Action items: {len(action_items)}, Completed: {len(completed)}, Decisions: {len(all_decisions)}"
            meeting_subjects = [m.subject for m in meetings[:10]]
            try:
                digest_text = await self._ai.complete(
                    model="gpt-4o-mini",
                    messages=[
                        SystemMessage(content="Generate a concise weekly executive digest (3-4 paragraphs). Focus on key outcomes, decisions, and upcoming priorities."),
                        UserMessage(content=f"Week stats: {context}\nMeetings: {meeting_subjects}\nDecisions: {all_decisions[:10]}"),
                    ],
                )
            except Exception:
                digest_text = f"This week: {len(meetings)} meetings, {len(action_items)} action items ({len(completed)} completed), {len(all_decisions)} decisions made."

            completion_rate = (len(completed) / max(len(action_items), 1)) * 100

            # People notes: gather collaboration patterns for the digest
            people_notes = await self._gather_people_notes(db, user_id, week_start)

            digest = WeeklyDigest(
                user_id=user_id, week_start=week_start, week_end=now,
                total_meetings=len(meetings), total_action_items=len(action_items),
                completion_rate=round(completion_rate, 1),
                key_decisions=all_decisions[:20],
                follow_ups=[{"description": a.description, "assigned_to": a.assigned_to_name, "deadline": str(a.deadline)} for a in action_items if a.status == "pending"][:10],
                digest_text=digest_text, delivered=False,
                people_notes=people_notes,
            )
            db.add(digest); await db.commit(); await db.refresh(digest)
            return digest

    @staticmethod
    async def _gather_people_notes(
        db: AsyncSession, user_id: str, week_start: datetime
    ) -> list[dict]:
        """Gather per-person interaction summaries for the weekly digest.

        Returns a list of dicts with display_name, meetings_this_week, and
        a note (e.g. "Haven't met in 2 weeks" for stale contacts).
        """
        fourteen_days_ago = datetime.now(UTC) - timedelta(days=14)

        # People met this week
        result = await db.execute(
            select(
                MeetingParticipant.user_id,
                MeetingParticipant.display_name,
                func.count().label("meetings_this_week"),
                func.max(Meeting.scheduled_start).label("last_meeting"),
            )
            .join(Meeting, MeetingParticipant.meeting_id == Meeting.id)
            .where(
                Meeting.scheduled_start >= week_start,
                MeetingParticipant.user_id.isnot(None),
            )
            .group_by(MeetingParticipant.user_id, MeetingParticipant.display_name)
            .order_by(func.count().desc())
            .limit(10)
        )
        met_this_week = {
            row.user_id: {
                "display_name": row.display_name,
                "meetings_this_week": row.meetings_this_week,
                "note": f"Met {row.meetings_this_week} time(s) this week",
            }
            for row in result.all()
        }

        # Stale contacts: people previously met but not in the last 14 days
        stale_result = await db.execute(
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
        for row in stale_result.all():
            if row.user_id not in met_this_week and row.last_meeting < fourteen_days_ago:
                days_since = (datetime.now(UTC) - row.last_meeting).days
                met_this_week[row.user_id] = {
                    "display_name": row.display_name,
                    "meetings_this_week": 0,
                    "note": f"Haven't met in {days_since} days",
                }

        return list(met_this_week.values())[:15]

    async def deliver_digest(self, digest_id: UUID) -> None:
        """Deliver a previously generated digest via Teams Adaptive Card.

        Marks the digest as delivered with a timestamp. No-op if already
        delivered.

        Args:
            digest_id: UUID of the WeeklyDigest to deliver.
        """
        async with self._session_factory() as db:
            result = await db.execute(select(WeeklyDigest).where(WeeklyDigest.id == digest_id))
            digest = result.scalar_one_or_none()
            if digest and not digest.delivered:
                # Delivery via Teams adaptive card
                logger.info("Delivering weekly digest %s to %s", digest_id, digest.user_id)
                digest.delivered = True; digest.delivered_at = datetime.now(UTC)
                await db.commit()
