"""Pydantic v2 schemas for weekly digests."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DigestFollowUp(BaseModel):
    """A pending follow-up item in the digest."""

    description: str
    assigned_to: str | None = None
    deadline: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DigestPeopleNote(BaseModel):
    """Per-person collaboration note."""

    display_name: str
    meetings_this_week: int = 0
    note: str = ""

    model_config = ConfigDict(from_attributes=True)


class WeeklyDigestResponse(BaseModel):
    """Weekly executive digest response."""

    id: uuid.UUID
    user_id: str
    week_start: date
    week_end: date
    total_meetings: int = 0
    total_action_items: int = 0
    completion_rate: float = 0.0
    key_decisions: list[Any] = []
    follow_ups: list[DigestFollowUp] = []
    people_notes: list[DigestPeopleNote] = []
    digest_text: str | None = None
    delivered: bool = False
    delivered_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DigestGenerateRequest(BaseModel):
    """Request body for triggering digest generation."""

    user_id: str
