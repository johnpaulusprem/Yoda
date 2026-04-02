"""Detect contradictions between current and past meeting decisions."""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_foundation.models.summary import MeetingSummary
from yoda_foundation.models.insight import MeetingInsight

logger = logging.getLogger(__name__)

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "for", "of", "in",
    "on", "at", "by", "with", "and", "or", "but", "not", "this", "that",
    "it", "we", "they", "from", "will", "has", "have", "had", "be", "been",
}

_CONTRADICTION_PAIRS = [
    ("increase", "decrease"),
    ("approve", "reject"),
    ("start", "stop"),
    ("hire", "freeze"),
    ("expand", "reduce"),
    ("prioritize", "deprioritize"),
    ("pursue", "abandon"),
    ("accelerate", "delay"),
    ("add", "remove"),
]


class ConflictDetectionService:
    """Compares new decisions against past decisions using keyword overlap."""

    async def check_for_conflicts(
        self, db: AsyncSession, meeting_id: str | _uuid.UUID, new_decisions: list[dict]
    ) -> list[dict]:
        """Compare new decisions against past 90 days of decisions.

        Returns list of conflict dicts:
            {new_decision, past_decision, past_meeting_id, similarity_reason}
        """
        # Ensure meeting_id is a proper UUID for SQLAlchemy comparison
        if isinstance(meeting_id, str):
            meeting_id = _uuid.UUID(meeting_id)

        cutoff = datetime.now(UTC) - timedelta(days=90)
        result = await db.execute(
            select(MeetingSummary).where(
                MeetingSummary.created_at >= cutoff,
                MeetingSummary.meeting_id != meeting_id,
            )
        )
        past_summaries = result.scalars().all()

        conflicts: list[dict] = []
        for new_dec in new_decisions:
            new_text = new_dec.get("decision", "").lower()
            new_keywords = set(new_text.split()) - _STOP_WORDS

            for past_summary in past_summaries:
                past_decisions = past_summary.decisions or []
                for past_dec in past_decisions:
                    past_text = past_dec.get("decision", "").lower()
                    past_keywords = set(past_text.split()) - _STOP_WORDS

                    overlap = new_keywords & past_keywords
                    if len(overlap) >= 3:
                        for word_a, word_b in _CONTRADICTION_PAIRS:
                            if (word_a in new_text and word_b in past_text) or \
                               (word_b in new_text and word_a in past_text):
                                conflicts.append({
                                    "new_decision": new_dec.get("decision"),
                                    "past_decision": past_dec.get("decision"),
                                    "past_meeting_id": str(past_summary.meeting_id),
                                    "similarity_reason": (
                                        f"Contradicting terms: {word_a}/{word_b}, "
                                        f"shared context: {', '.join(list(overlap)[:5])}"
                                    ),
                                })
                                break

        # Store as insights
        for conflict in conflicts:
            insight = MeetingInsight(
                meeting_id=meeting_id,
                insight_type="conflict_detection",
                severity="warning",
                data=conflict,
            )
            db.add(insight)

        if conflicts:
            await db.commit()
            logger.info("Detected %d conflicts for meeting %s", len(conflicts), meeting_id)

        return conflicts

    async def check_reversals_in_series(
        self, db: AsyncSession, meeting_id: str | _uuid.UUID, subject: str
    ) -> list[dict]:
        """Check if decisions in this meeting reverse decisions from prior
        meetings with the same subject (recurring series).

        Args:
            db: Async SQLAlchemy session.
            meeting_id: UUID of the current meeting.
            subject: Subject line to match recurring meetings against.

        Returns:
            List of reversal dicts with new_decision, past_decision,
            past_meeting_id, and reason fields.
        """
        from yoda_foundation.models.meeting import Meeting

        if isinstance(meeting_id, str):
            meeting_id = _uuid.UUID(meeting_id)

        # Get current meeting summary
        current_result = await db.execute(
            select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id)
        )
        current_summary = current_result.scalar_one_or_none()
        if not current_summary or not current_summary.decisions:
            return []

        # Find past meetings with the same subject
        past_meetings_result = await db.execute(
            select(Meeting.id).where(
                Meeting.subject == subject,
                Meeting.id != meeting_id,
            )
        )
        past_meeting_ids = [row[0] for row in past_meetings_result.all()]

        if not past_meeting_ids:
            return []

        # Get summaries from those meetings
        past_summaries_result = await db.execute(
            select(MeetingSummary).where(
                MeetingSummary.meeting_id.in_(past_meeting_ids)
            )
        )
        past_summaries = past_summaries_result.scalars().all()

        reversals: list[dict] = []
        for new_dec in current_summary.decisions:
            new_text = new_dec.get("decision", "").lower()
            new_keywords = set(new_text.split()) - _STOP_WORDS

            for past_summary in past_summaries:
                for past_dec in (past_summary.decisions or []):
                    past_text = past_dec.get("decision", "").lower()
                    past_keywords = set(past_text.split()) - _STOP_WORDS

                    overlap = new_keywords & past_keywords
                    if len(overlap) >= 2:
                        for word_a, word_b in _CONTRADICTION_PAIRS:
                            if (word_a in new_text and word_b in past_text) or \
                               (word_b in new_text and word_a in past_text):
                                reversals.append({
                                    "new_decision": new_dec.get("decision"),
                                    "past_decision": past_dec.get("decision"),
                                    "past_meeting_id": str(past_summary.meeting_id),
                                    "reason": (
                                        f"Reversal in series '{subject}': "
                                        f"{word_a} vs {word_b}"
                                    ),
                                })
                                break

        if reversals:
            for reversal in reversals:
                insight = MeetingInsight(
                    meeting_id=meeting_id,
                    insight_type="decision_reversal",
                    severity="warning",
                    data=reversal,
                )
                db.add(insight)
            await db.commit()
            logger.info(
                "Detected %d reversals in series '%s' for meeting %s",
                len(reversals), subject, meeting_id,
            )

        return reversals
