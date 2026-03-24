"""Pydantic v2 response schemas for transcript segments."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class TranscriptSegmentResponse(BaseModel):
    """API response schema for a single transcript segment.

    Each segment represents one speaker's utterance within the meeting
    transcript. Serialized from the TranscriptSegment ORM model via
    ``from_attributes=True``.

    Attributes:
        id: Unique segment identifier (UUID).
        meeting_id: Foreign key to the parent meeting.
        speaker_name: Display name of the speaker.
        speaker_id: Azure AD object ID of the speaker, if resolved.
        text: Transcribed text content.
        start_time: Segment start offset in seconds from meeting start.
        end_time: Segment end offset in seconds from meeting start.
        confidence: Speech-to-text confidence score (0.0--1.0).
        sequence_number: Ordering index within the transcript.
        language: Detected language code (e.g. ``en-US``).
    """

    id: uuid.UUID
    meeting_id: uuid.UUID
    speaker_name: str
    speaker_id: str | None = None
    text: str
    start_time: float
    end_time: float
    confidence: float | None = None
    sequence_number: int
    language: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TranscriptResponse(BaseModel):
    """Paginated response wrapper containing transcript segments for a meeting.

    Attributes:
        segments: List of transcript segment objects for the current page.
        total: Total number of segments in the meeting transcript.
    """

    segments: list[TranscriptSegmentResponse]
    total: int
