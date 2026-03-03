"""Document management routes with RAG ingestion and semantic search."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cxo_ai_companion.dependencies import get_db
from cxo_ai_companion.security.auth_dependency import get_current_user
from cxo_ai_companion.security.context import SecurityContext
from cxo_ai_companion.models.document import Document
from cxo_ai_companion.schemas.document import DocumentListResponse, DocumentResponse

router = APIRouter()


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    meeting_id: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> DocumentListResponse:
    """List documents, optionally filtered by meeting ID."""
    query = select(Document)
    if meeting_id:
        query = query.where(Document.meeting_id == meeting_id)
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
    from cxo_ai_companion.dependencies import get_retriever

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

    from cxo_ai_companion.dependencies import (
        get_ingestion_pipeline,
        get_session_factory,
    )

    logger = logging.getLogger(__name__)
    try:
        from cxo_ai_companion.services.document_service import DocumentService

        service = DocumentService(
            graph_connector=None,
            db_session_factory=get_session_factory(),
            ingestion_pipeline=get_ingestion_pipeline(),
        )
        await service.process_document(document_id)
    except Exception:
        logger.exception("Background document processing failed for %s", document_id)
