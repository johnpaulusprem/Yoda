"""Pydantic v2 schemas for pre-meeting briefs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AttendeeContextResponse(BaseModel):
    """Contextual information about a meeting attendee."""

    user_id: str | None = None
    display_name: str
    email: str | None = None
    role: str = "attendee"
    job_title: str | None = None
    department: str | None = None
    recent_interactions: int = 0
    overdue_action_items: int = 0
    last_meeting_subject: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PastDecisionResponse(BaseModel):
    """A decision from a past meeting."""

    decision_text: str
    meeting_subject: str
    meeting_date: datetime
    context: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RelatedDocumentResponse(BaseModel):
    """A document related to the upcoming meeting."""

    title: str
    source: str
    source_url: str | None = None
    relevance_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class EmailThreadResponse(BaseModel):
    """An email thread related to the upcoming meeting."""

    subject: str
    sender_name: str = ""
    sender_email: str = ""
    snippet: str = ""
    received_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PreMeetingBriefResponse(BaseModel):
    """Complete pre-meeting brief aggregating context for an upcoming meeting."""

    meeting_id: uuid.UUID
    meeting_subject: str
    scheduled_start: datetime
    attendees: list[AttendeeContextResponse] = []
    past_decisions: list[PastDecisionResponse] = []
    related_documents: list[RelatedDocumentResponse] = []
    recent_email_subjects: list[str] = []
    recent_email_threads: list[EmailThreadResponse] = []
    suggested_questions: list[str] = []
    executive_summary: str = ""
    generated_at: datetime

    model_config = ConfigDict(from_attributes=True)
