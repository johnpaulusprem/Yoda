"""ActionItem ORM model for meeting-derived tasks and follow-ups."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cxo_ai_companion.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from cxo_ai_companion.models.meeting import Meeting


class ActionItem(Base, UUIDMixin, TimestampMixin):
    """A task or follow-up extracted from a meeting transcript by the AI processor.

    Supports the full action-item lifecycle: extraction, assignment,
    nudge reminders, snoozing, and completion tracking.

    Attributes:
        meeting_id: FK to the parent Meeting.
        description: What needs to be done.
        assigned_to_name: Display name of the person responsible.
        assigned_to_user_id: Azure AD object ID, if resolved.
        assigned_to_email: Email of the assignee, if available.
        deadline: Due date/time extracted or inferred from discussion (UTC).
        priority: Urgency level (high | medium | low).
        status: Workflow state (pending | in_progress | completed | cancelled).
        source_quote: Verbatim transcript excerpt that prompted this item.
        nudge_count: Number of reminder nudges sent so far.
        last_nudge_at: Timestamp of the most recent nudge (UTC).
        completed_at: Timestamp when the item was marked complete (UTC).
        snoozed_until: If snoozed, the datetime after which nudges resume (UTC).
        confidence: AI confidence score (0.0-1.0) for the extraction.
    """

    __tablename__ = "action_items"

    meeting_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
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
    )  # high | medium | low
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )  # pending | in_progress | completed | cancelled
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    nudge_count: Mapped[int] = mapped_column(Integer, default=0)
    last_nudge_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    snoozed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    meeting: Mapped[Meeting] = relationship(back_populates="action_items")
