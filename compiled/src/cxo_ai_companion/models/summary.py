"""MeetingSummary ORM model for AI-generated meeting summaries."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cxo_ai_companion.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from cxo_ai_companion.models.meeting import Meeting


class MeetingSummary(Base, UUIDMixin, TimestampMixin):
    """AI-generated summary produced after a meeting ends.

    Created by the AI processing pipeline from the assembled transcript.
    Contains the narrative summary, structured decisions, key topics,
    and delivery tracking metadata.

    Attributes:
        meeting_id: FK to the parent Meeting (one-to-one).
        summary_text: Full narrative summary of the meeting.
        decisions: JSON list of decisions made during the meeting.
        key_topics: JSON list of major topics discussed.
        unresolved_questions: JSON list of open questions still pending.
        model_used: AI model identifier used for generation (e.g. gpt-4o-mini).
        processing_time_seconds: Wall-clock time the AI pipeline took.
        delivered: Whether the summary has been sent to recipients.
        delivered_at: Timestamp of successful delivery (UTC).
        delivery_channel: Channel used for delivery (chat | email | teams).
    """

    __tablename__ = "meeting_summaries"

    meeting_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("meetings.id"),
        unique=True,
        nullable=False,
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    decisions: Mapped[list[dict]] = mapped_column(JSON, default=list)
    key_topics: Mapped[list[dict]] = mapped_column(JSON, default=list)
    unresolved_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    model_used: Mapped[str] = mapped_column(String, nullable=False)
    processing_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_channel: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # chat | email | teams

    meeting: Mapped[Meeting] = relationship(back_populates="summary")
