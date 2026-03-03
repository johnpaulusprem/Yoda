"""Meeting repository with domain-specific queries."""
from __future__ import annotations
from datetime import UTC, datetime, timedelta
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from cxo_ai_companion.data_access.base.repository import GenericRepository
from cxo_ai_companion.models.meeting import Meeting

class MeetingRepository(GenericRepository[Meeting]):
    """Data access layer for Meeting entities.

    Extends GenericRepository with meeting-specific queries like
    status filtering, date-range lookups, and eager-loaded detail views.
    Uses flush() for writes -- commit is handled by the route-level session.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Meeting)

    async def get_by_status(self, status: str, limit: int = 20, offset: int = 0) -> list[Meeting]:
        """Fetch meetings filtered by status with pagination.

        Args:
            status: Meeting status string (e.g. "scheduled", "completed").
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            Meetings ordered by scheduled_start descending.
        """
        result = await self._session.execute(select(Meeting).where(Meeting.status == status).order_by(Meeting.scheduled_start.desc()).limit(limit).offset(offset))
        return list(result.scalars().all())

    async def get_with_details(self, meeting_id: UUID) -> Meeting | None:
        """Fetch a meeting with all relationships eagerly loaded.

        Loads participants, summary, and action items in a single query
        using selectinload.

        Args:
            meeting_id: UUID of the meeting to retrieve.

        Returns:
            Meeting with loaded relationships, or None if not found.
        """
        result = await self._session.execute(select(Meeting).where(Meeting.id == meeting_id).options(selectinload(Meeting.summary), selectinload(Meeting.action_items), selectinload(Meeting.participants)))
        return result.scalar_one_or_none()

    async def get_upcoming(self, hours: int = 24) -> list[Meeting]:
        """Fetch scheduled meetings starting within the given time window.

        Args:
            hours: Lookahead window in hours from now.

        Returns:
            Scheduled meetings ordered by start time ascending.
        """
        now = datetime.now(UTC); cutoff = now + timedelta(hours=hours)
        result = await self._session.execute(select(Meeting).where(Meeting.scheduled_start >= now, Meeting.scheduled_start <= cutoff, Meeting.status == "scheduled").order_by(Meeting.scheduled_start))
        return list(result.scalars().all())

    async def get_completed_without_summary(self) -> list[Meeting]:
        """Fetch completed meetings that do not yet have a generated summary.

        Returns:
            Completed meetings missing a summary, ordered by start time descending.
        """
        result = await self._session.execute(select(Meeting).where(Meeting.status == "completed").options(selectinload(Meeting.summary)).order_by(Meeting.scheduled_start.desc()))
        return [m for m in result.scalars().all() if m.summary is None]

    async def update_status(self, meeting_id: UUID, status: str) -> None:
        """Update a meeting's status field and flush.

        Args:
            meeting_id: UUID of the meeting to update.
            status: New status value.
        """
        meeting = await self.get_by_id(meeting_id)
        if meeting: meeting.status = status; await self._session.flush()
