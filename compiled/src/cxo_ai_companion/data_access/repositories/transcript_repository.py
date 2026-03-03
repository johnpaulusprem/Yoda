"""Transcript repository."""
from __future__ import annotations
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from cxo_ai_companion.data_access.base.repository import GenericRepository
from cxo_ai_companion.models.transcript import TranscriptSegment

class TranscriptRepository(GenericRepository[TranscriptSegment]):
    """Data access layer for TranscriptSegment entities.

    Extends GenericRepository with meeting-scoped queries, segment
    counting, and bulk insertion for real-time transcript ingestion.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TranscriptSegment)

    async def get_by_meeting(self, meeting_id: UUID) -> list[TranscriptSegment]:
        """Fetch all transcript segments for a meeting, ordered by sequence number.

        Args:
            meeting_id: UUID of the meeting.

        Returns:
            Segments in chronological order.
        """
        result = await self._session.execute(select(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id).order_by(TranscriptSegment.sequence_number))
        return list(result.scalars().all())

    async def get_segment_count(self, meeting_id: UUID) -> int:
        """Return the total number of transcript segments for a meeting.

        Args:
            meeting_id: UUID of the meeting.

        Returns:
            Integer count of segments.
        """
        result = await self._session.execute(select(func.count()).select_from(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id))
        return result.scalar_one()

    async def bulk_create(self, segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
        """Insert multiple transcript segments in a single flush.

        Args:
            segments: List of TranscriptSegment instances to persist.

        Returns:
            The same list of segments after flushing to the database.
        """
        self._session.add_all(segments); await self._session.flush(); return segments
