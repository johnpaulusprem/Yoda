"""Pydantic v2 schemas for pre-meeting briefs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AttendeeContextResponse(BaseModel):
    """Contextual information about a meeting attendee within a pre-meeting brief.

    Provides background on each attendee including their role, recent
    interaction history, and outstanding obligations. Serialized via
    ``from_attributes=True``.

    Attributes:
        user_id: Azure AD object ID, if resolved.
        display_name: Attendee's display name.
        email: Email address, if available.
        role: Role in the meeting (e.g. attendee, organizer).
        job_title: Attendee's job title from the directory.
        department: Attendee's department from the directory.
        recent_interactions: Number of recent meetings with this attendee.
        overdue_action_items: Count of overdue action items assigned to this attendee.
        last_meeting_subject: Subject of the most recent meeting with this attendee.
    """

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
    """A decision from a past meeting, surfaced in a pre-meeting brief.

    Serialized via ``from_attributes=True``.

    Attributes:
        decision_text: Text of the past decision.
        meeting_subject: Subject of the meeting where the decision was made.
        meeting_date: Date/time of that meeting.
        context: Additional context around the decision.
    """

    decision_text: str
    meeting_subject: str
    meeting_date: datetime
    context: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RelatedDocumentResponse(BaseModel):
    """A document related to the upcoming meeting, surfaced in a pre-meeting brief.

    Serialized via ``from_attributes=True``.

    Attributes:
        title: Document title or filename.
        source: Origin of the document (sharepoint, onedrive, email_attachment).
        source_url: URL to access the document.
        relevance_reason: AI-generated explanation of why this document is relevant.
    """

    title: str
    source: str
    source_url: str | None = None
    relevance_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class EmailThreadResponse(BaseModel):
    """An email thread related to the upcoming meeting, surfaced in a pre-meeting brief.

    Serialized via ``from_attributes=True``.

    Attributes:
        subject: Email thread subject line.
        sender_name: Display name of the sender.
        sender_email: Email address of the sender.
        snippet: Preview excerpt of the email body.
        received_at: Timestamp when the email was received.
    """

    subject: str
    sender_name: str = ""
    sender_email: str = ""
    snippet: str = ""
    received_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PreMeetingBriefResponse(BaseModel):
    """Complete pre-meeting brief aggregating context for an upcoming meeting.

    Combines attendee profiles, past decisions, related documents, recent
    emails, and AI-suggested questions into a single briefing package.
    Serialized via ``from_attributes=True``.

    Attributes:
        meeting_id: Identifier of the upcoming meeting.
        meeting_subject: Subject line of the meeting.
        scheduled_start: Planned start time (UTC).
        attendees: Contextual profiles for each attendee.
        past_decisions: Relevant decisions from prior meetings.
        related_documents: Documents surfaced as relevant.
        recent_email_subjects: Subject lines of recent related emails.
        recent_email_threads: Full email thread previews.
        suggested_questions: AI-generated questions to raise in the meeting.
        executive_summary: Short AI-generated executive summary of context.
        generated_at: Timestamp when the brief was generated.
    """

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
