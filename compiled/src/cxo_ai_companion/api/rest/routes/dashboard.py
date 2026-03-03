"""Dashboard API routes for CXO executive view."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import chain

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from cxo_ai_companion.dependencies import get_db
from cxo_ai_companion.security.auth_dependency import get_current_user
from cxo_ai_companion.security.context import SecurityContext
from cxo_ai_companion.data_access.repositories import MeetingRepository, ActionItemRepository
from cxo_ai_companion.models.document import Document
from cxo_ai_companion.models.summary import MeetingSummary
from cxo_ai_companion.models.action_item import ActionItem
from cxo_ai_companion.models.meeting import Meeting

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db), ctx: SecurityContext = Depends(get_current_user)):
    """Return executive dashboard KPIs: meetings today, pending/overdue actions, completion rate, and docs to review."""
    m_repo = MeetingRepository(db)
    a_repo = ActionItemRepository(db)
    upcoming = await m_repo.get_upcoming(hours=24)
    overdue = await a_repo.get_overdue()
    pending = await a_repo.find_by(status="pending")
    completed = await a_repo.find_by(status="completed")
    total = len(pending) + len(completed) + len(overdue)
    rate = (len(completed) / total * 100) if total > 0 else 0

    # Docs pending review
    docs_to_review_r = await db.execute(
        select(func.count()).select_from(Document).where(Document.review_status == "pending_review")
    )
    docs_to_review = docs_to_review_r.scalar_one()

    return {
        "meetings_today": len(upcoming),
        "pending_actions": len(pending),
        "overdue_actions": len(overdue),
        "completion_rate": round(rate, 1),
        "docs_to_review": docs_to_review,
    }


@router.get("/attention-items")
async def get_attention_items(db: AsyncSession = Depends(get_db), ctx: SecurityContext = Depends(get_current_user)):
    """Return items needing attention: overdue and due-soon action items."""
    a_repo = ActionItemRepository(db)
    overdue = await a_repo.get_overdue()
    due_soon = await a_repo.get_due_soon(hours=48)
    items = [{"type": "overdue", "description": a.description, "deadline": str(a.deadline), "meeting_id": str(a.meeting_id)} for a in overdue[:5]]
    items += [{"type": "due_soon", "description": a.description, "deadline": str(a.deadline), "meeting_id": str(a.meeting_id)} for a in due_soon[:5]]
    return {"items": items, "total": len(items)}


@router.get("/activity-feed")
async def get_activity_feed(
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Extended activity feed with summaries, action items, and document uploads."""
    feed: list[dict] = []

    # Completed meetings with summaries (summary_ready)
    summary_result = await db.execute(
        select(MeetingSummary)
        .join(Meeting, MeetingSummary.meeting_id == Meeting.id)
        .order_by(MeetingSummary.created_at.desc())
        .limit(limit)
    )
    for s in summary_result.scalars().all():
        feed.append({
            "type": "summary_ready",
            "title": f"Summary ready for meeting",
            "meeting_id": str(s.meeting_id),
            "timestamp": str(s.created_at),
        })

    # Recently assigned action items (action_assigned)
    action_result = await db.execute(
        select(ActionItem)
        .where(ActionItem.status == "pending")
        .order_by(ActionItem.created_at.desc())
        .limit(limit)
    )
    for a in action_result.scalars().all():
        feed.append({
            "type": "action_assigned",
            "title": a.description[:80],
            "assigned_to": a.assigned_to_name,
            "meeting_id": str(a.meeting_id),
            "timestamp": str(a.created_at),
        })

    # Recent document uploads (document_shared)
    doc_result = await db.execute(
        select(Document)
        .order_by(Document.created_at.desc())
        .limit(limit)
    )
    for d in doc_result.scalars().all():
        feed.append({
            "type": "document_shared",
            "title": d.title,
            "document_id": str(d.id),
            "timestamp": str(d.created_at),
        })

    # Sort by timestamp descending, take top `limit`
    feed.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    feed = feed[:limit]

    return {"items": feed, "total": len(feed)}
