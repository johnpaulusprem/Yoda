"""Pydantic response schemas for meeting summaries."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SummaryResponse(BaseModel):
    """Response schema for a meeting summary produced by the AI processor."""

    id: uuid.UUID
    meeting_id: uuid.UUID
    summary_text: str
    decisions: list[dict]
    key_topics: list[dict]
    unresolved_questions: list[str]
    model_used: str
    processing_time_seconds: float
    delivered: bool
    delivered_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
