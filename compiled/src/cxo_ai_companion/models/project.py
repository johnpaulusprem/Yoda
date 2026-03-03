"""Project and ProjectMeeting ORM models for cross-meeting project tracking."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Column, Date, Float, ForeignKey, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cxo_ai_companion.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from cxo_ai_companion.models.meeting import Meeting


# Association table for project-meeting many-to-many
project_meetings_table = Table(
    "project_meetings",
    Base.metadata,
    Column("project_id", PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("meeting_id", PG_UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True),
)


class Project(Base, UUIDMixin, TimestampMixin):
    """A project that groups related meetings and tracks cross-meeting progress.

    Projects are created manually or inferred by the AI from recurring
    meeting topics. They aggregate meetings via a many-to-many join table.

    Attributes:
        name: Human-readable project name.
        description: Optional longer description or goals.
        owner_user_id: Azure AD object ID of the project owner.
        status: Lifecycle state (active | on_hold | completed).
        completion_pct: Estimated completion percentage (0.0-100.0).
        target_date: Desired completion date, if set.
        current_phase: Free-text label for the current project phase.
    """

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )  # active | on_hold | completed
    completion_pct: Mapped[float] = mapped_column(Float, default=0.0)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_phase: Mapped[str | None] = mapped_column(String, nullable=True)

    meetings: Mapped[list[Meeting]] = relationship(
        secondary=project_meetings_table, lazy="selectin"
    )
