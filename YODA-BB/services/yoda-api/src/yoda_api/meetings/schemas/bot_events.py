"""Pydantic schemas for Browser Bot event payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TranscriptSegmentIn(BaseModel):
    sequence: int = Field(ge=0)
    speaker_id: str = Field(default="", max_length=256)
    speaker_name: str = Field(default="Unknown", max_length=512)
    text: str = Field(min_length=1, max_length=10_000)
    start_time_sec: float = Field(ge=0)
    end_time_sec: float = Field(ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    is_final: bool = True
    source: str | None = Field(default=None, max_length=10)  # "caption" or "audio"


class TranscriptChunkIn(BaseModel):
    meeting_id: str = Field(min_length=1, max_length=64)
    bot_instance_id: str = Field(min_length=1, max_length=256)
    segments: list[TranscriptSegmentIn] = Field(max_length=500)

    @field_validator("meeting_id")
    @classmethod
    def validate_meeting_id_is_uuid(cls, v: str) -> str:
        import uuid

        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("meeting_id must be a valid UUID")
        return v


class SpeakerEventIn(BaseModel):
    meeting_id: str = Field(min_length=1, max_length=64)
    bot_instance_id: str = Field(min_length=1, max_length=256)
    event_type: Literal["SPEAKER_START", "SPEAKER_END"]
    participant_id: str = Field(min_length=1, max_length=256)
    participant_name: str | None = Field(default=None, max_length=512)
    relative_timestamp_ms: float = Field(ge=0)

    @field_validator("meeting_id")
    @classmethod
    def validate_meeting_id_is_uuid(cls, v: str) -> str:
        import uuid

        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("meeting_id must be a valid UUID")
        return v


class BotLifecycleEventIn(BaseModel):
    meeting_id: str = Field(min_length=1, max_length=64)
    bot_instance_id: str = Field(min_length=1, max_length=256)
    event_type: Literal[
        "bot_joined", "participants_updated", "meeting_ended", "bot_error"
    ]
    timestamp: datetime
    data: dict | None = None

    @field_validator("meeting_id")
    @classmethod
    def validate_meeting_id_is_uuid(cls, v: str) -> str:
        import uuid

        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("meeting_id must be a valid UUID")
        return v
