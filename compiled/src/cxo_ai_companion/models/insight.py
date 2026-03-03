"""MeetingInsight and WeeklyDigest ORM models for CXO analytics features."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cxo_ai_companion.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from cxo_ai_companion.models.meeting import Meeting


class MeetingInsight(Base, UUIDMixin, TimestampMixin):
    """An AI-generated insight derived from meeting analysis.

    Insight types include conflict detection, sentiment analysis,
    participation metrics, and topic trends. Insights are surfaced
    in the CXO dashboard and weekly digest.

    Attributes:
        meeting_id: FK to the parent Meeting.
        insight_type: Category (conflict_detection | sentiment | participation | topic_trend).
        data: JSON payload with type-specific insight details.
        severity: Alert level (info | warning | critical).
    """

    __tablename__ = "meeting_insights"

    meeting_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
    )
    insight_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # conflict_detection | sentiment | participation | topic_trend
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    severity: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # info | warning | critical

    meeting: Mapped[Meeting] = relationship(back_populates="insights")


class WeeklyDigest(Base, UUIDMixin, TimestampMixin):
    """Aggregated weekly summary delivered to CXO users.

    Rolls up meetings, action items, decisions, and follow-ups for
    a given user over a Monday-to-Friday window.

    Attributes:
        user_id: Azure AD object ID of the recipient.
        week_start: Monday of the digest week.
        week_end: Friday (or Sunday) of the digest week.
        total_meetings: Number of meetings held during the week.
        total_action_items: Number of action items created during the week.
        completion_rate: Fraction (0.0-1.0) of action items completed.
        key_decisions: JSON list of notable decisions across all meetings.
        follow_ups: JSON list of outstanding follow-up items.
        people_notes: JSON list of per-person highlights or observations.
        digest_text: Full narrative text of the digest, if generated.
        delivered: Whether the digest has been sent to the user.
        delivered_at: Timestamp of successful delivery (UTC).
    """

    __tablename__ = "weekly_digests"

    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    total_meetings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_action_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    key_decisions: Mapped[list[dict]] = mapped_column(JSON, default=list)
    follow_ups: Mapped[list[dict]] = mapped_column(JSON, default=list)
    people_notes: Mapped[list[dict]] = mapped_column(JSON, default=list)
    digest_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
