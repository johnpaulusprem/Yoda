"""Pydantic request/response schemas for meetings."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict


def _extract_thread_id_from_join_url(join_url: str) -> str:
    """Extract Teams thread ID from join URL, or return a placeholder."""
    match = re.search(r"meetup-join/([^/]+)", join_url)
    if match:
        return unquote(match.group(1))
    return join_url or "test-thread"


class CreateMeetingRequest(BaseModel):
    """Request body for creating a test meeting (bot join testing)."""

    join_url: str
    subject: str = "Test meeting"
    organizer_name: str = "Test Organizer"
    organizer_email: str = "test@example.com"

from app.schemas.action_item import ActionItemResponse
from app.schemas.summary import SummaryResponse


class ParticipantResponse(BaseModel):
    """Response schema for a meeting participant."""

    id: uuid.UUID
    display_name: str
    email: str | None
    role: str
    joined_at: datetime | None
    left_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class MeetingResponse(BaseModel):
    """Response schema for a meeting list item."""

    id: uuid.UUID
    teams_meeting_id: str
    thread_id: str
    join_url: str
    subject: str
    organizer_id: str
    organizer_name: str
    organizer_email: str
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    status: str
    participant_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MeetingDetailResponse(MeetingResponse):
    """Extended meeting response with summary, action items, and participants."""

    summary: SummaryResponse | None = None
    action_items: list[ActionItemResponse] = []
    participants: list[ParticipantResponse] = []


class MeetingListResponse(BaseModel):
    """Paginated response for listing meetings."""

    items: list[MeetingResponse]
    total: int
