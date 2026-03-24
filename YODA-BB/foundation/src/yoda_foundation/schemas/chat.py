"""Pydantic v2 schemas for the Ask AI / RAG chat feature."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageRequest(BaseModel):
    """Request body for sending a message to the AI assistant.

    Attributes:
        content: The user's question or message text (required, min 1 char).
        session_id: Existing session ID to continue a conversation (optional).
            Omit to start a new session.
    """

    content: str = Field(
        min_length=1,
        description="The user's question or message",
    )
    session_id: uuid.UUID | None = Field(
        default=None,
        description="Existing session ID to continue a conversation. Omit to start new.",
    )


class ChatSourceCitation(BaseModel):
    """A single source citation returned alongside an AI response.

    Citations link the AI answer back to the original documents or
    meetings used as context during RAG retrieval.

    Attributes:
        title: Title of the source document or meeting.
        url: URL to the source, if available.
        snippet: Relevant excerpt from the source.
        document_id: UUID of the cited document, if applicable.
        meeting_id: UUID of the cited meeting, if applicable.
    """

    title: str
    url: str | None = None
    snippet: str | None = None
    document_id: uuid.UUID | None = None
    meeting_id: uuid.UUID | None = None


class ChatMessageResponse(BaseModel):
    """API response schema for a single chat message (user or assistant).

    Serialized from the ChatMessage ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique message identifier (UUID).
        session_id: Parent chat session identifier.
        role: Message author role (``user`` or ``assistant``).
        content: Message text content.
        sources: Source citations for AI-generated answers.
        model_used: AI model identifier used for this response.
        tokens_used: Total token count consumed by this response.
        created_at: Timestamp when the message was created.
    """

    id: uuid.UUID
    session_id: uuid.UUID
    role: str  # user | assistant
    content: str
    sources: list[ChatSourceCitation] | None = None
    model_used: str | None = None
    tokens_used: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionResponse(BaseModel):
    """API response schema for a chat session (conversation thread).

    Serialized from the ChatSession ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique session identifier (UUID).
        user_id: Azure AD object ID of the session owner.
        title: Auto-generated or user-set session title.
        last_message_at: Timestamp of the most recent message.
        created_at: Session creation timestamp.
        messages: Ordered list of messages in the session.
    """

    id: uuid.UUID
    user_id: str
    title: str | None = None
    last_message_at: datetime | None = None
    created_at: datetime
    messages: list[ChatMessageResponse] = []

    model_config = ConfigDict(from_attributes=True)


class ChatSessionListResponse(BaseModel):
    """Paginated response wrapper for listing chat sessions.

    Attributes:
        items: List of chat session objects for the current page.
        total: Total number of sessions matching the query.
    """

    items: list[ChatSessionResponse]
    total: int
