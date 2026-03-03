import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class MeetingSummary(Base, TimestampMixin):
    __tablename__ = "meeting_summaries"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id"), unique=True, nullable=False
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

    meeting: Mapped["Meeting"] = relationship(back_populates="summary")
