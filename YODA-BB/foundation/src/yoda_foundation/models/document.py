"""Document ORM model for meeting-related files and RAG source material."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yoda_foundation.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from yoda_foundation.models.meeting import Meeting


class Document(Base, UUIDMixin, TimestampMixin):
    """A document associated with a meeting or uploaded for RAG indexing.

    Sources include SharePoint, OneDrive, and email attachments.
    Once processed, the extracted text is chunked and embedded for use
    by the Ask AI / RAG chat pipeline.

    Attributes:
        meeting_id: FK to the associated Meeting, if any.
        title: Human-readable document title.
        source: Origin of the file (sharepoint | onedrive | email_attachment).
        source_url: Original URL where the document was fetched from.
        content_type: MIME type (e.g. application/pdf).
        content_hash: SHA-256 hash of the file bytes for deduplication.
        extracted_text: Full plain-text content after parsing.
        embedding_id: Reference to the vector-store entry, if indexed.
        status: Processing state (pending | processed | failed).
        uploaded_by: User ID or email of the uploader.
        file_size_bytes: Size of the original file in bytes.
        review_status: Moderation state (none | pending_review | approved | rejected).
    """

    __tablename__ = "documents"

    meeting_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(
        String, nullable=False
    )  # sharepoint | onedrive | email_attachment
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    content_type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # MIME type, e.g. application/pdf
    content_hash: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # SHA-256 for dedup
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Reference to vector store entry
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )  # pending | processed | failed
    uploaded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    review_status: Mapped[str] = mapped_column(
        String, nullable=False, default="none"
    )  # none | pending_review | approved | rejected

    # --- Wireframe-driven additions for Documents view ---
    folder_path: Mapped[str | None] = mapped_column(String, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shared_by: Mapped[str | None] = mapped_column(String, nullable=True)
    shared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    priority: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # high | medium | low
    last_modified_by: Mapped[str | None] = mapped_column(String, nullable=True)
    graph_item_id: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True
    )

    # --- Classification fields ---
    category: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # e.g. mbr, qbr, sow, status_report, etc.
    classification_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    suggested_tags: Mapped[dict[str, Any] | None] = mapped_column(
        "classification_tags", JSON, nullable=True
    )  # list of suggested tags from classifier

    meeting: Mapped[Meeting | None] = relationship(back_populates="documents", lazy="raise")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
        lazy="raise",
    )


class DocumentChunk(UUIDMixin, TimestampMixin, Base):
    """Individual chunk of a document with its vector embedding.

    Documents are split into overlapping chunks for retrieval-augmented
    generation. Each chunk stores its text, positional index, token count,
    and a 1536-dimension embedding vector for similarity search.

    Attributes:
        document_id: FK to the parent Document.
        chunk_index: Zero-based position of this chunk within the document.
        content: Plain-text content of the chunk.
        embedding: 1536-dimension vector (pgvector) for similarity search.
        token_count: Number of tokens in this chunk (used for context budgeting).
        metadata_: Optional JSON metadata (mapped to the ``metadata`` column).
    """

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(1536), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )

    # Relationships
    document: Mapped[Document] = relationship("Document", back_populates="chunks", lazy="raise")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
    )
