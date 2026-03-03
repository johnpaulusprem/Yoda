"""Global search API route."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cxo_ai_companion.dependencies import get_db
from cxo_ai_companion.models.meeting import Meeting
from cxo_ai_companion.models.action_item import ActionItem
from cxo_ai_companion.models.document import Document
from cxo_ai_companion.schemas.search import SearchResponse, SearchResultItem

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=SearchResponse)
async def global_search(
    q: str = Query(..., min_length=1, description="Search query"),
    types: str = Query("meetings,documents,actions", description="Comma-separated types to search"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search across meetings, documents, and action items."""
    search_types = [t.strip() for t in types.split(",")]
    pattern = f"%{q}%"
    results: list[SearchResultItem] = []

    if "meetings" in search_types:
        meeting_result = await db.execute(
            select(Meeting)
            .where(Meeting.subject.ilike(pattern))
            .limit(limit)
        )
        for m in meeting_result.scalars().all():
            results.append(
                SearchResultItem(
                    type="meeting",
                    id=m.id,
                    title=m.subject,
                    snippet=f"Scheduled: {m.scheduled_start.isoformat()} | Status: {m.status}",
                    score=1.0,
                    metadata={"status": m.status, "organizer": m.organizer_name},
                )
            )

    if "actions" in search_types:
        action_result = await db.execute(
            select(ActionItem)
            .where(ActionItem.description.ilike(pattern))
            .limit(limit)
        )
        for a in action_result.scalars().all():
            results.append(
                SearchResultItem(
                    type="action_item",
                    id=a.id,
                    title=a.description[:100],
                    snippet=f"Assigned to: {a.assigned_to_name} | Priority: {a.priority} | Status: {a.status}",
                    score=0.9,
                    metadata={"status": a.status, "priority": a.priority},
                )
            )

    if "documents" in search_types:
        doc_result = await db.execute(
            select(Document)
            .where(Document.title.ilike(pattern))
            .limit(limit)
        )
        for d in doc_result.scalars().all():
            results.append(
                SearchResultItem(
                    type="document",
                    id=d.id,
                    title=d.title,
                    snippet=f"Source: {d.source} | Status: {d.status}",
                    score=0.8,
                    metadata={"source": d.source, "content_type": d.content_type},
                )
            )

    # Sort by score descending, limit total
    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:limit]

    return SearchResponse(results=results, total=len(results), query=q)
