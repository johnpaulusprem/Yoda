"""Pydantic v2 schemas for AI-generated insights and weekly digests."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class InsightResponse(BaseModel):
    """API response schema for an AI-generated meeting insight.

    Serialized from the Insight ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique insight identifier (UUID).
        meeting_id: Foreign key to the parent meeting.
        insight_type: Category of insight (conflict_detection, sentiment,
            participation, topic_trend).
        data: Structured insight payload (type-specific JSON).
        severity: Urgency level (info, warning, critical).
        created_at: Timestamp when the insight was generated.
    """

    id: uuid.UUID
    meeting_id: uuid.UUID
    insight_type: str  # conflict_detection | sentiment | participation | topic_trend
    data: dict
    severity: str | None = None  # info | warning | critical
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InsightListResponse(BaseModel):
    """Paginated response wrapper for listing insights.

    Attributes:
        items: List of insight response objects for the current page.
        total: Total number of insights matching the query.
    """

    items: list[InsightResponse]
    total: int


class WeeklyDigestResponse(BaseModel):
    """API response schema for a weekly digest summarizing meeting activity.

    Serialized from the WeeklyDigest ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique digest identifier (UUID).
        user_id: Azure AD object ID of the recipient.
        week_start: Start date of the digest period (Monday).
        week_end: End date of the digest period (Sunday).
        total_meetings: Number of meetings held during the week.
        total_action_items: Number of action items created during the week.
        completion_rate: Percentage of action items completed (0.0--100.0).
        key_decisions: Important decisions made during the week.
        follow_ups: Items requiring follow-up attention.
        digest_text: Full AI-generated digest narrative.
        delivered: Whether the digest has been sent to the user.
        delivered_at: Timestamp of delivery, if delivered.
        created_at: Record creation timestamp.
    """

    id: uuid.UUID
    user_id: str
    week_start: date
    week_end: date
    total_meetings: int
    total_action_items: int
    completion_rate: float
    key_decisions: list[dict]
    follow_ups: list[dict]
    digest_text: str | None = None
    delivered: bool
    delivered_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
