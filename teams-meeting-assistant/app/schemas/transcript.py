"""Pydantic response schemas for transcript segments."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class TranscriptSegmentResponse(BaseModel):
    """Response schema for a single transcript segment."""

    id: uuid.UUID
    meeting_id: uuid.UUID
    speaker_name: str
    speaker_id: str | None
    text: str
    start_time: float
    end_time: float
    confidence: float | None
    sequence_number: int

    model_config = ConfigDict(from_attributes=True)


class TranscriptResponse(BaseModel):
    """Paginated response containing transcript segments for a meeting."""

    segments: list[TranscriptSegmentResponse]
    total: int
