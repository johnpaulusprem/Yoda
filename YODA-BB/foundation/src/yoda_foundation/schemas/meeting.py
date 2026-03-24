"""Pydantic v2 request/response schemas for meetings."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from yoda_foundation.schemas.action_item import ActionItemResponse
from yoda_foundation.schemas.summary import SummaryResponse


# ---------------------------------------------------------------------------
# Participant schemas
# ---------------------------------------------------------------------------


class ParticipantResponse(BaseModel):
    """API response schema for a meeting participant.

    Serialized from the Participant ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique participant record identifier (UUID).
        display_name: Participant's display name from Teams.
        email: Email address, if available.
        user_id: Azure AD object ID, if resolved.
        role: Participant role (e.g. organizer, attendee, presenter).
        joined_at: Timestamp when the participant joined the call.
        left_at: Timestamp when the participant left the call.
    """

    id: uuid.UUID
    display_name: str
    email: str | None = None
    user_id: str | None = None
    role: str
    joined_at: datetime | None = None
    left_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Meeting response schemas
# ---------------------------------------------------------------------------


class MeetingResponse(BaseModel):
    """API response schema for a meeting entity.

    Serialized from the Meeting ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique meeting identifier (UUID).
        teams_meeting_id: Microsoft Teams meeting ID.
        thread_id: Teams chat thread ID associated with the meeting.
        join_url: Teams join URL for the meeting.
        subject: Meeting title / subject line.
        organizer_id: Azure AD object ID of the organizer.
        organizer_name: Display name of the meeting organizer.
        organizer_email: Email address of the organizer.
        scheduled_start: Planned start time (UTC).
        scheduled_end: Planned end time (UTC).
        actual_start: Actual start time, set when the call begins.
        actual_end: Actual end time, set when the call ends.
        status: Current lifecycle state (scheduled, in_progress, completed, failed, cancelled).
        recording_url: URL to the call recording, if available.
        participant_count: Number of participants who joined.
        join_status: Computed join state for the UI (upcoming, join_now, in_progress, ended).
        created_at: Record creation timestamp.
        updated_at: Record last-update timestamp.
    """

    id: uuid.UUID
    teams_meeting_id: str
    thread_id: str | None = None
    join_url: str
    subject: str
    organizer_id: str | None = None
    organizer_name: str
    organizer_email: str
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    status: str
    recording_url: str | None = None
    participant_count: int = 0
    join_status: str = "upcoming"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    def model_post_init(self, __context: object) -> None:
        """Compute join_status based on current time and meeting state."""
        from datetime import UTC, timedelta

        now = datetime.now(UTC)
        start = self.scheduled_start.replace(tzinfo=UTC) if self.scheduled_start.tzinfo is None else self.scheduled_start
        end = self.scheduled_end.replace(tzinfo=UTC) if self.scheduled_end.tzinfo is None else self.scheduled_end

        if self.status == "in_progress":
            self.join_status = "in_progress"
        elif self.status in ("completed", "cancelled", "failed"):
            self.join_status = "ended"
        elif now >= start - timedelta(minutes=5) and now <= end:
            self.join_status = "join_now"
        else:
            self.join_status = "upcoming"


class MeetingDetailResponse(MeetingResponse):
    """Extended meeting response including nested summary, action items, and participants.

    Inherits all fields from ``MeetingResponse`` and adds related sub-resources
    for a full meeting detail view.

    Attributes:
        summary: AI-generated meeting summary, if processing is complete.
        action_items: List of action items extracted from the meeting.
        participants: List of participants who joined the call.
    """

    summary: SummaryResponse | None = None
    action_items: list[ActionItemResponse] = []
    participants: list[ParticipantResponse] = []


class MeetingWithTagsResponse(MeetingResponse):
    """Meeting response extended with computed tags for calendar view.

    Inherits all fields from ``MeetingResponse``. Tags are computed
    server-side based on meeting metadata (e.g. recurring, has-actions).

    Attributes:
        tags: Computed tag labels for UI filtering and display.
    """

    tags: list[str] = []


class MeetingListResponse(BaseModel):
    """Paginated response wrapper for listing meetings.

    Attributes:
        items: List of meeting response objects for the current page.
            Uses ``MeetingWithTagsResponse`` so computed tags are included.
        total: Total number of meetings matching the query.
    """

    items: list[MeetingWithTagsResponse]
    total: int


# ---------------------------------------------------------------------------
# Meeting request schemas
# ---------------------------------------------------------------------------


class MeetingCreateRequest(BaseModel):
    """Request body for manually registering a meeting to be tracked.

    All required fields must be supplied; optional fields default to ``None``.

    Attributes:
        teams_meeting_id: Microsoft Teams meeting ID (required).
        subject: Meeting title (required).
        organizer_name: Display name of the organizer (required).
        organizer_email: Email of the organizer (required).
        join_url: Teams join URL (required).
        scheduled_start: Planned start time in UTC (required).
        scheduled_end: Planned end time in UTC (required).
        thread_id: Teams chat thread ID (optional).
        organizer_id: Azure AD object ID of the organizer (optional).
    """

    teams_meeting_id: str
    subject: str
    organizer_name: str
    organizer_email: str
    join_url: str
    scheduled_start: datetime
    scheduled_end: datetime
    thread_id: str | None = None
    organizer_id: str | None = None


class MeetingUpdateRequest(BaseModel):
    """Partial update (PATCH) schema for a meeting.

    All fields are optional. Only supplied fields will be updated.

    Attributes:
        subject: Updated meeting title.
        status: New lifecycle state (scheduled, in_progress, completed, failed, cancelled).
        actual_start: Actual call start time.
        actual_end: Actual call end time.
        recording_url: URL to the call recording.
        acs_call_connection_id: ACS call connection identifier.
        participant_count: Updated participant count.
    """

    subject: str | None = None
    status: str | None = Field(
        default=None,
        description="New status: scheduled, in_progress, completed, failed, cancelled",
    )
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    recording_url: str | None = None
    acs_call_connection_id: str | None = None
    participant_count: int | None = None


# ---------------------------------------------------------------------------
# Monolith-compatible aliases & helpers
# ---------------------------------------------------------------------------


class CreateMeetingRequest(BaseModel):
    """Request body for creating a test meeting (bot join testing).

    Used by the meeting-service routes for quick manual meeting creation
    with just a Teams join URL.

    Attributes:
        join_url: Teams meeting join URL (required).
        subject: Meeting title (defaults to 'Test meeting').
        organizer_name: Display name of the organizer.
        organizer_email: Email of the organizer.
    """

    join_url: str
    subject: str = "Test meeting"
    organizer_name: str = "Test Organizer"
    organizer_email: str = "test@example.com"


def _extract_thread_id_from_join_url(join_url: str) -> str:
    """Extract Teams thread ID from a meeting join URL, or return a placeholder.

    Teams join URLs contain the thread ID encoded in the URL path, e.g.::

        https://teams.microsoft.com/l/meetup-join/19%3ameeting_<id>%40thread.v2/...

    Args:
        join_url: The full Teams meeting join URL.

    Returns:
        The decoded thread ID, or the raw URL / placeholder if extraction fails.
    """
    import re
    from urllib.parse import unquote

    match = re.search(r"meetup-join/([^/]+)", join_url)
    if match:
        return unquote(match.group(1))
    return join_url or "test-thread"
