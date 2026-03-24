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

    # Wireframe-driven additions
    folder_path: str | None = None
    page_count: int | None = None
    shared_by: str | None = None
    shared_at: datetime | None = None
    priority: str | None = None
    last_modified_by: str | None = None

    # Classification
    category: str | None = None
    classification_confidence: float | None = None
    suggested_tags: list[str] | None = None

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


class DocumentSyncResponse(BaseModel):
    """Response for document sync operations.

    Attributes:
        synced: Number of documents synced from Graph API.
        new_documents: Newly created document records.
    """

    synced: int
    new_documents: list[DocumentResponse]


class NeedsReviewResponse(BaseModel):
    """Documents needing user review with priority tags.

    Attributes:
        items: Documents pending review.
        total: Total count of documents needing review.
    """

    items: list[DocumentResponse]
    total: int


class ClassificationResponse(BaseModel):
    """Result of classifying a document.

    Attributes:
        document_id: UUID of the classified document.
        category: Detected document category (e.g. mbr, sow, risk_document).
        category_label: Human-readable label for the category.
        confidence: Confidence score (0.0 to 1.0).
        suggested_priority: Suggested priority level (high, medium, low).
        suggested_tags: Auto-suggested tags for the document.
        top_matches: Top category matches with scores (detailed mode).
    """

    document_id: uuid.UUID
    category: str
    category_label: str
    confidence: float
    suggested_priority: str
    suggested_tags: list[str]
    top_matches: list[dict[str, float]] = Field(default_factory=list)


class MeetingDocumentsResponse(BaseModel):
    """Documents related to a specific meeting.

    Attributes:
        items: Documents linked to the meeting.
        total: Total count.
        meeting_subject: Subject of the associated meeting.
    """

    items: list[DocumentResponse]
    total: int
    meeting_subject: str | None = None
