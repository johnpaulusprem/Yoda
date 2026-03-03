"""Conflict detection service for identifying contradictory decisions across meetings."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from cxo_ai_companion.models.insight import MeetingInsight
from cxo_ai_companion.models.meeting import Meeting, MeetingParticipant
from cxo_ai_companion.models.summary import MeetingSummary

logger = logging.getLogger(__name__)


class ConflictDetectionService:
    """Detects conflicting decisions across meetings.

    Compares current meeting decisions against the last 90 days of decisions
    from meetings with overlapping participants using keyword-based negation
    pair detection (e.g., approve/reject, increase/decrease).

    Args:
        db_session_factory: Async session factory for querying summaries.
        dspy_adapter: Optional DSPy adapter for advanced conflict detection
            (reserved for future use).
    """

    def __init__(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        dspy_adapter: object | None = None,
    ) -> None:
        self._session_factory = db_session_factory
        self._dspy_adapter = dspy_adapter

    async def detect_conflicts(self, meeting_id: UUID) -> list[dict]:
        """Compare current meeting decisions against past 90 days for conflicts.

        Fetches decisions from meetings with overlapping participants and
        applies keyword-based negation pair analysis. Persists any detected
        conflicts as MeetingInsight records.

        Args:
            meeting_id: UUID of the meeting whose decisions to analyze.

        Returns:
            List of conflict dicts with current_decision, past_decision,
            conflict_type, severity, and past_meeting_id fields.
        """
        async with self._session_factory() as db:
            # 1. Fetch current meeting summary
            result = await db.execute(
                select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id)
            )
            current_summary = result.scalar_one_or_none()
            if not current_summary or not current_summary.decisions:
                return []

            # 2. Fetch current meeting's participants
            participant_result = await db.execute(
                select(MeetingParticipant.user_id).where(
                    MeetingParticipant.meeting_id == meeting_id,
                    MeetingParticipant.user_id.isnot(None),
                )
            )
            participant_ids = [row[0] for row in participant_result.all()]

            # 3. Fetch past 90 days of decisions from overlapping-participant meetings
            ninety_days_ago = datetime.now(UTC) - timedelta(days=90)
            past_query = (
                select(MeetingSummary)
                .join(Meeting, MeetingSummary.meeting_id == Meeting.id)
                .join(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
                .where(
                    MeetingSummary.meeting_id != meeting_id,
                    Meeting.scheduled_start >= ninety_days_ago,
                    Meeting.status == "completed",
                )
            )
            if participant_ids:
                past_query = past_query.where(
                    MeetingParticipant.user_id.in_(participant_ids)
                )
            past_query = past_query.distinct().limit(20)

            past_result = await db.execute(past_query)
            past_summaries = past_result.scalars().all()

            past_decisions = []
            for ps in past_summaries:
                for d in ps.decisions or []:
                    past_decisions.append({
                        "decision": d.get("decision", "") if isinstance(d, dict) else str(d),
                        "meeting_id": str(ps.meeting_id),
                    })

            if not past_decisions:
                return []

            # 4. Simple keyword-based conflict detection (no external AI call needed)
            conflicts = self._detect_keyword_conflicts(
                current_summary.decisions, past_decisions
            )

            # 5. Store results as MeetingInsight
            if conflicts:
                insight = MeetingInsight(
                    meeting_id=meeting_id,
                    insight_type="conflict_detection",
                    data={"conflicts": conflicts},
                    severity="warning" if conflicts else "info",
                )
                db.add(insight)
                await db.flush()
                await db.commit()

            return conflicts

    @staticmethod
    def _detect_keyword_conflicts(
        current_decisions: list[dict],
        past_decisions: list[dict],
    ) -> list[dict]:
        """Simple keyword-based conflict detection between decision sets."""
        conflicts: list[dict] = []
        negation_pairs = [
            ("approve", "reject"), ("increase", "decrease"), ("add", "remove"),
            ("start", "stop"), ("enable", "disable"), ("expand", "reduce"),
            ("accept", "decline"), ("hire", "freeze"),
        ]

        for current in current_decisions:
            current_text = (
                current.get("decision", "") if isinstance(current, dict) else str(current)
            ).lower()
            if not current_text:
                continue

            for past in past_decisions:
                past_text = past.get("decision", "").lower()
                if not past_text:
                    continue

                for word_a, word_b in negation_pairs:
                    if (word_a in current_text and word_b in past_text) or (
                        word_b in current_text and word_a in past_text
                    ):
                        # Check for topic overlap (shared significant words)
                        current_words = set(current_text.split())
                        past_words = set(past_text.split())
                        common = current_words & past_words - {
                            "the", "a", "an", "to", "and", "or", "of", "in", "for", "is", "was",
                        }
                        if len(common) >= 2:
                            conflicts.append({
                                "current_decision": current.get("decision", "") if isinstance(current, dict) else str(current),
                                "past_decision": past.get("decision", ""),
                                "conflict_type": "potential_reversal",
                                "severity": "warning",
                                "past_meeting_id": past.get("meeting_id"),
                            })
                            break

        return conflicts
