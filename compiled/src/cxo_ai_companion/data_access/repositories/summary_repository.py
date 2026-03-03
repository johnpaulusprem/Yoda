"""Summary repository."""
from __future__ import annotations
from datetime import UTC, datetime
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from cxo_ai_companion.data_access.base.repository import GenericRepository
from cxo_ai_companion.models.summary import MeetingSummary

class SummaryRepository(GenericRepository[MeetingSummary]):
    """Data access layer for MeetingSummary entities.

    Extends GenericRepository with meeting-scoped lookups, delivery
    tracking, and undelivered summary queries for the delivery pipeline.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MeetingSummary)

    async def get_by_meeting(self, meeting_id: UUID) -> MeetingSummary | None:
        """Fetch the summary associated with a specific meeting.

        Args:
            meeting_id: UUID of the meeting.

        Returns:
            The meeting summary, or None if not yet generated.
        """
        result = await self._session.execute(select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id))
        return result.scalar_one_or_none()

    async def get_undelivered(self) -> list[MeetingSummary]:
        """Fetch all summaries that have not yet been delivered.

        Returns:
            Undelivered summaries ordered by creation time ascending.
        """
        result = await self._session.execute(select(MeetingSummary).where(MeetingSummary.delivered == False).order_by(MeetingSummary.created_at))
        return list(result.scalars().all())

    async def mark_delivered(self, summary_id: UUID) -> None:
        """Mark a summary as delivered with the current timestamp.

        Args:
            summary_id: UUID of the summary to mark.
        """
        summary = await self.get_by_id(summary_id)
        if summary: summary.delivered = True; summary.delivered_at = datetime.now(UTC); await self._session.flush()
