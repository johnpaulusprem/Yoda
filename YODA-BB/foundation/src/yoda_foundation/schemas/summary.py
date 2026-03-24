"""Pydantic v2 response schemas for meeting summaries."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DecisionResponse(BaseModel):
    """A single decision extracted from a meeting summary.

    Serialized from the Decision ORM model via ``from_attributes=True``.

    Attributes:
        description: Text of the decision that was made.
        made_by: Name of the person who made or proposed the decision.
        context: Surrounding discussion context for the decision.
    """

    description: str
    made_by: str | None = None
    context: str | None = None

    model_config = ConfigDict(from_attributes=True)


class KeyTopicResponse(BaseModel):
    """A key topic discussed during a meeting.

    Serialized from the KeyTopic ORM model via ``from_attributes=True``.

    Attributes:
        topic: Short label or title of the discussed topic.
        duration_minutes: Estimated time spent on this topic, in minutes.
        participants: Names of participants who contributed to this topic.
    """

    topic: str
    duration_minutes: float | None = None
    participants: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class SummaryResponse(BaseModel):
    """API response schema for a meeting summary produced by the AI processor.

    Serialized from the Summary ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique summary identifier (UUID).
        meeting_id: Foreign key to the parent meeting.
        summary_text: Full AI-generated summary text.
        decisions: List of decisions extracted from the transcript.
        key_topics: List of key topics discussed.
        unresolved_questions: Open questions that were not resolved.
        model_used: AI model identifier used for generation.
        processing_time_seconds: Wall-clock time taken to generate the summary.
        delivered: Whether the summary has been delivered to stakeholders.
        delivered_at: Timestamp of delivery, if delivered.
        delivery_channel: Channel used for delivery (chat, email).
    """

    id: uuid.UUID
    meeting_id: uuid.UUID
    summary_text: str
    decisions: list[dict]
    key_topics: list[dict]
    unresolved_questions: list[str]
    model_used: str
    processing_time_seconds: float
    delivered: bool
    delivered_at: datetime | None = None
    delivery_channel: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SummaryUpdateRequest(BaseModel):
    """Partial update (PATCH) request for a meeting summary.

    All fields are optional. Only supplied fields will be updated.

    Attributes:
        summary_text: Revised summary text.
        decisions: Updated list of decisions.
        key_topics: Updated list of key topics.
        unresolved_questions: Updated list of unresolved questions.
    """

    summary_text: str | None = None
    decisions: list[dict] | None = None
    key_topics: list[dict] | None = None
    unresolved_questions: list[str] | None = None


class SummaryShareRequest(BaseModel):
    """Request to share a meeting summary via specified channels.

    Attributes:
        channels: Delivery channels to use (``chat``, ``email``). Defaults to ``["chat"]``.
    """

    channels: list[str] = ["chat"]  # chat | email


class SummaryShareResponse(BaseModel):
    """Response confirming a summary was shared.

    Attributes:
        shared: Whether the share operation succeeded.
        channels: Channels the summary was shared through.
        shared_at: Timestamp when the summary was shared.
    """

    shared: bool
    channels: list[str]
    shared_at: datetime
