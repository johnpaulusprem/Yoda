"""Meeting and MeetingParticipant ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yoda_foundation.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from yoda_foundation.models.action_item import ActionItem
    from yoda_foundation.models.document import Document
    from yoda_foundation.models.insight import MeetingInsight
    from yoda_foundation.models.summary import MeetingSummary
    from yoda_foundation.models.transcript import TranscriptSegment


class Meeting(Base, UUIDMixin, TimestampMixin):
    """Core meeting entity representing a Teams calendar event.

    Tracks the full lifecycle from scheduled -> in_progress -> completed,
    storing the Teams join URL, ACS connection, and relationships to
    participants, transcripts, summaries, action items, and documents.

    Attributes:
        teams_meeting_id: Unique Teams meeting identifier from Graph API.
        thread_id: Teams chat thread ID associated with the meeting.
        join_url: Teams join URL used by ACS to connect the bot.
        subject: Meeting title from the calendar event.
        organizer_name: Display name of the meeting organizer.
        organizer_email: Email of the meeting organizer.
        status: Lifecycle state (scheduled | in_progress | completed | cancelled | failed).
        scheduled_start: Planned start time (UTC).
        scheduled_end: Planned end time (UTC).
        actual_start: Real start time once the bot joins (UTC).
        actual_end: Real end time once the bot disconnects (UTC).
        acs_call_connection_id: ACS Call Automation connection ID for the active call.
        recording_url: URL to the stored meeting recording, if available.
        participant_count: Number of participants detected during the meeting.
    """

    __tablename__ = "meetings"

    teams_meeting_id: Mapped[str] = mapped_column(String, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    join_url: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    organizer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    organizer_name: Mapped[str] = mapped_column(String, nullable=False)
    organizer_email: Mapped[str] = mapped_column(String, nullable=False)
    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scheduled_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    actual_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="scheduled"
    )  # scheduled | in_progress | completed | failed | cancelled
    acs_call_connection_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    recording_url: Mapped[str | None] = mapped_column(String, nullable=True)
    participant_count: Mapped[int] = mapped_column(Integer, default=0)

    # -- Relationships --------------------------------------------------------
    participants: Mapped[list[MeetingParticipant]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="raise"
    )
    transcript_segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="raise"
    )
    summary: Mapped[MeetingSummary | None] = relationship(
        back_populates="meeting", uselist=False, cascade="all, delete-orphan", lazy="raise"
    )
    action_items: Mapped[list[ActionItem]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="raise"
    )
    documents: Mapped[list[Document]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="raise"
    )
    insights: Mapped[list[MeetingInsight]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", lazy="raise"
    )


class MeetingParticipant(Base, UUIDMixin, TimestampMixin):
    """A participant who attended or was invited to a meeting.

    Captures identity information and join/leave timestamps for each
    person detected in the Teams call by ACS or Graph.

    Attributes:
        meeting_id: FK to the parent Meeting.
        user_id: Azure AD object ID of the participant, if resolved.
        display_name: Human-readable name shown in Teams.
        email: Email address of the participant, if available.
        role: Participant role (organizer | attendee | presenter).
        joined_at: Timestamp when the participant joined the call (UTC).
        left_at: Timestamp when the participant left the call (UTC).
    """

    __tablename__ = "meeting_participants"

    meeting_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(
        String, nullable=False, default="attendee"
    )  # organizer | attendee | presenter
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    meeting: Mapped[Meeting] = relationship(back_populates="participants", lazy="raise")
