"""TranscriptSegment ORM model for meeting transcription data."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
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
    source: Mapped[str | None] = mapped_column(String(10), nullable=True)

    meeting: Mapped[Meeting] = relationship(back_populates="transcript_segments", lazy="raise")

    __table_args__ = (
        sa.UniqueConstraint("meeting_id", "sequence_number", name="uq_transcript_meeting_sequence"),
    )


class SpeakerEvent(Base, UUIDMixin):
    """Browser-bot SPEAKER_START/SPEAKER_END events for overlap-based speaker mapping."""

    __tablename__ = "speaker_events"

    meeting_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    bot_instance_id: Mapped[str] = mapped_column(String(256), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    participant_id: Mapped[str] = mapped_column(String(256), nullable=False)
    participant_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    relative_timestamp_ms: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False,
    )
