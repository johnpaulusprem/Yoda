import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ActionItem(Base, TimestampMixin):
    __tablename__ = "action_items"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to_name: Mapped[str] = mapped_column(String, nullable=False)
    assigned_to_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    assigned_to_email: Mapped[str | None] = mapped_column(String, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    priority: Mapped[str] = mapped_column(
        String, nullable=False, default="medium"
    )  # high, medium, low
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )  # pending, in_progress, completed, snoozed
    nudge_count: Mapped[int] = mapped_column(Integer, default=0)
    last_nudged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    snoozed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    meeting: Mapped["Meeting"] = relationship(back_populates="action_items")
