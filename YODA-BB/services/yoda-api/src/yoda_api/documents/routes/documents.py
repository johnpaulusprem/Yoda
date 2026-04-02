"""Document management routes with RAG ingestion and semantic search."""

from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_api.dependencies import get_db, get_document_service
from yoda_foundation.security.auth_dependency import get_current_user
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.models.document import Document
from yoda_foundation.schemas.document import (
    ClassificationResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentSyncResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =========================================================================
# Fixed-path routes (MUST be defined before /{document_id} to avoid
# FastAPI interpreting "sync", "recent", etc. as a UUID path param)
# =========================================================================


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    meeting_id: UUID | None = Query(None),
    doc_type: str | None = Query(
        None,
        description="Filter by type: presentations|spreadsheets|documents|pdfs",
    ),
    sort: str = Query("recent", description="Sort: recent|name"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> DocumentListResponse:
    """List documents, optionally filtered by meeting ID and document type.

    Results are scoped to documents uploaded by or shared with the
    authenticated user.
    """
    user_id = ctx.user_id
    query = select(Document).where(
        or_(
            Document.uploaded_by == user_id,
            Document.shared_by == user_id,
        )
    )
    if meeting_id:
        query = query.where(Document.meeting_id == meeting_id)

    # Map doc_type to MIME type LIKE filters
    _type_mime_map: dict[str, list[str]] = {
        "presentations": [
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.ms-powerpoint",
        ],
        "spreadsheets": [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        ],
        "documents": [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ],
        "pdfs": [
            "application/pdf",
        ],
    }
    if doc_type and doc_type in _type_mime_map:
        query = query.where(Document.content_type.in_(_type_mime_map[doc_type]))

    if sort == "name":
        query = query.order_by(Document.title)
    else:
        query = query.order_by(Document.updated_at.desc())

    result = await db.execute(query.limit(limit))
    docs = result.scalars().all()
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        total=len(docs),
    )


@router.get("/search")
async def search_documents(
    q: str = Query(..., min_length=1, description="Semantic search query"),
    k: int = Query(5, ge=1, le=50),
    ctx: SecurityContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Semantic search across all indexed documents via the RAG retriever."""
    from yoda_api.dependencies import get_retriever

    retriever = get_retriever()
    result = await retriever.retrieve(query=q, k=k)
    return {
        "query": q,
        "total_results": result.total_results,
        "execution_time_ms": result.execution_time_ms,
        "results": [
            {
                "id": doc.id,
                "content": doc.content[:500],
                "score": doc.score,
                "metadata": doc.metadata,
            }
            for doc in result.documents
        ],
    }


@router.post("/sync", response_model=DocumentSyncResponse)
async def sync_documents(
    service: Any = Depends(get_document_service),
    ctx: SecurityContext = Depends(get_current_user),
) -> DocumentSyncResponse:
    """Trigger SharePoint/OneDrive sync for the authenticated user.

    Pulls the user's recent documents from Microsoft Graph and persists
    any newly discovered items in the local database.
    """
    new_docs = await service.sync_from_graph(ctx.user_id)
    return DocumentSyncResponse(
        synced=len(new_docs),
        new_documents=[DocumentResponse.model_validate(d) for d in new_docs],
    )


@router.get("/shared-with-me", response_model=DocumentListResponse)
async def shared_with_me(
    limit: int = Query(20, ge=1, le=100),
    service: Any = Depends(get_document_service),
    ctx: SecurityContext = Depends(get_current_user),
) -> DocumentListResponse:
    """Get documents shared with the current user."""
    docs = await service.get_shared_with_me(ctx.user_id)
    limited = docs[:limit]
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in limited],
        total=len(docs),
    )


@router.get("/needs-review", response_model=DocumentListResponse)
async def needs_review(
    service: Any = Depends(get_document_service),
    ctx: SecurityContext = Depends(get_current_user),
) -> DocumentListResponse:
    """Get documents that need the user's review.

    Returns documents with review_status 'pending_review' or 'action_required',
    ordered by priority (high first) then shared_at descending.
    """
    docs = await service.get_needs_review(ctx.user_id)
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        total=len(docs),
    )


@router.get("/meeting-related")
async def meeting_related_documents(
    service: Any = Depends(get_document_service),
    ctx: SecurityContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Get documents related to today's meetings.

    Cross-references today's calendar events with local documents and
    Graph event attachments.
    """
    results = await service.get_meeting_documents_for_today(ctx.user_id)
    return {
        "meetings": results,
        "total_meetings": len(results),
    }


@router.get("/recent", response_model=DocumentListResponse)
async def recent_documents(
    doc_type: str | None = Query(
        None,
        description="Filter: presentations|spreadsheets|documents|pdfs",
    ),
    sort: str = Query(
        "recently_updated",
        description="Sort: recently_updated|most_relevant|shared_with_me",
    ),
    limit: int = Query(20, ge=1, le=100),
    service: Any = Depends(get_document_service),
    ctx: SecurityContext = Depends(get_current_user),
) -> DocumentListResponse:
    """Get recently updated documents with optional type filter.

    Supports the Documents view wireframe with type filtering and sort order.
    """
    docs = await service.get_recently_updated(
        user_id=ctx.user_id,
        doc_type=doc_type,
        limit=limit,
    )
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        total=len(docs),
    )


@router.post("/index-emails")
async def index_emails(
    days: int = Query(7, ge=1, le=30, description="How many days back to fetch"),
    limit: int = Query(50, ge=1, le=200, description="Max emails to index"),
    service: Any = Depends(get_document_service),
    ctx: SecurityContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Index recent emails from Microsoft Graph into the RAG pipeline.

    Fetches emails from the user's mailbox, creates Document records, and
    runs them through the ingestion pipeline for semantic search.
    """
    try:
        indexed = await service.index_emails(
            user_id=ctx.user_id, days=days, limit=limit
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "indexed_count": len(indexed),
        "emails": [
            {
                "id": str(doc.id),
                "title": doc.title,
                "status": doc.status,
            }
            for doc in indexed
        ],
    }


@router.post("/classify-text", response_model=ClassificationResponse)
async def classify_text(
    text: str = Query(..., min_length=10, description="Text to classify"),
    filename: str | None = Query(None, description="Optional filename for hints"),
    content_type: str | None = Query(None, description="Optional MIME type"),
    ctx: SecurityContext = Depends(get_current_user),
) -> ClassificationResponse:
    """Classify arbitrary text without creating a document.

    Useful for previewing classification before upload.
    """
    from yoda_api.dependencies import get_document_classifier
    from yoda_foundation.rag.classification.document_classifier import CATEGORY_LABELS

    classifier = get_document_classifier()
    if filename or content_type:
        result = await classifier.classify_file(
            text=text, filename=filename, content_type=content_type
        )
    else:
        result = await classifier.classify(text)

    return ClassificationResponse(
        document_id=uuid.UUID(int=0),  # no document yet
        category=result.category,
        category_label=CATEGORY_LABELS.get(result.category, result.category),
        confidence=result.confidence,
        suggested_priority=result.suggested_priority,
        suggested_tags=result.suggested_tags,
    )


# =========================================================================
# Path-parameter routes (AFTER all fixed-path routes)
# =========================================================================


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> DocumentResponse:
    """Retrieve a single document by ID."""
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(doc)


@router.post("/{document_id}/classify", response_model=ClassificationResponse)
async def classify_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> ClassificationResponse:
    """Classify an existing document and persist the result.

    Uses extracted text (or title as fallback) to classify the document,
    then updates the document record with category, confidence, priority,
    and suggested tags.
    """
    from yoda_api.dependencies import get_document_classifier
    from yoda_foundation.rag.classification.document_classifier import CATEGORY_LABELS

    result_row = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result_row.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    text = doc.extracted_text or doc.title
    if not text:
        raise HTTPException(
            status_code=400,
            detail="Document has no text to classify (not yet processed?)",
        )

    classifier = get_document_classifier()
    classification = await classifier.classify_file(
        text=text,
        filename=doc.title,
        content_type=doc.content_type,
    )

    # Persist classification on the document
    doc.category = classification.category
    doc.classification_confidence = classification.confidence
    doc.priority = classification.suggested_priority
    doc.suggested_tags = classification.suggested_tags
    await db.flush()

    return ClassificationResponse(
        document_id=document_id,
        category=classification.category,
        category_label=CATEGORY_LABELS.get(classification.category, classification.category),
        confidence=classification.confidence,
        suggested_priority=classification.suggested_priority,
        suggested_tags=classification.suggested_tags,
    )


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile,
    title: str = Query(...),
    meeting_id: UUID | None = Query(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> DocumentResponse:
    """Upload a document and trigger async RAG ingestion."""
    content = await file.read()

    doc = Document(
        title=title,
        source="upload",
        content_type=file.content_type or "",
        file_size_bytes=len(content),
        uploaded_by=ctx.user_id,
        meeting_id=meeting_id,
        status="pending",
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)

    # Schedule background ingestion
    background_tasks.add_task(_process_document_background, doc.id)

    return DocumentResponse.model_validate(doc)


@router.post("/{document_id}/reprocess", status_code=202)
async def reprocess_document(
    document_id: UUID,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> dict[str, str]:
    """Re-index an existing document through the ingestion pipeline."""
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.status = "pending"
    await db.flush()

    background_tasks.add_task(_process_document_background, document_id)
    return {"status": "reprocessing", "document_id": str(document_id)}


async def _process_document_background(document_id: UUID) -> None:
    """Background task to process a document via the ingestion pipeline."""
    import logging

    from yoda_api.dependencies import (
        get_ingestion_pipeline,
        get_session_factory,
    )

    _logger = logging.getLogger(__name__)
    try:
        from yoda_api.documents.services.document_service import DocumentService

        service = DocumentService(
            graph_connector=None,
            db_session_factory=get_session_factory(),
            ingestion_pipeline=get_ingestion_pipeline(),
        )
        await service.process_document(document_id)
    except Exception:
        _logger.exception("Background document processing failed for %s", document_id)
