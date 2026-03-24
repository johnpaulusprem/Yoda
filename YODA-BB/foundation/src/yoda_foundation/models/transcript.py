"""TranscriptSegment ORM model for meeting transcription data."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yoda_foundation.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from yoda_foundation.models.meeting import Meeting


class TranscriptSegment(Base, UUIDMixin, TimestampMixin):
    """A single speaker turn extracted from the ACS real-time transcription stream.

    Segments arrive via WebSocket during the call and are buffered,
    reassembled per speaker, then persisted in sequence order.

    Attributes:
        meeting_id: FK to the parent Meeting.
        speaker_name: Display name of the speaker as reported by ACS.
        speaker_id: ACS or Azure AD identifier for the speaker, if resolved.
        text: Transcribed text content for this segment.
        start_time: Offset in seconds from the start of the call.
        end_time: Offset in seconds when this segment ends.
        confidence: Speech-to-text confidence score (0.0-1.0).
        sequence_number: Monotonically increasing order index within the meeting.
        language: BCP-47 language tag (defaults to en-US).
    """

    __tablename__ = "transcript_segments"

    meeting_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
    )
    speaker_name: Mapped[str] = mapped_column(String, nullable=False)
    speaker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str | None] = mapped_column(
        String, nullable=True, default="en-US"
    )

    meeting: Mapped[Meeting] = relationship(back_populates="transcript_segments", lazy="raise")
