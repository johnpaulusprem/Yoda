"""Pydantic v2 schemas for document management."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    """API response schema for a document ingested for RAG processing.

    Serialized from the Document ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique document identifier (UUID).
        meeting_id: Associated meeting, if the document is meeting-specific.
        title: Document title or filename.
        source: Origin of the document (sharepoint, onedrive, email_attachment).
        source_url: Original URL where the document can be accessed.
        content_type: MIME type of the document.
        content_hash: SHA-256 hash for deduplication.
        status: Processing status (pending, processed, failed).
        uploaded_by: User ID or name of the uploader.
        file_size_bytes: File size in bytes.
        review_status: Human review state (none, pending_review, approved, rejected).
        created_at: Record creation timestamp.
        updated_at: Record last-update timestamp.
    """

    id: uuid.UUID
    meeting_id: uuid.UUID | None = None
    title: str
    source: str  # sharepoint | onedrive | email_attachment
    source_url: str | None = None
    content_type: str | None = None
    content_hash: str | None = None
    status: str  # pending | processed | failed
    uploaded_by: str | None = None
    file_size_bytes: int | None = None
    review_status: str = "none"  # none | pending_review | approved | rejected
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    """Paginated response wrapper for listing documents.

    Attributes:
        items: List of document response objects for the current page.
        total: Total number of documents matching the query.
    """

    items: list[DocumentResponse]
    total: int
