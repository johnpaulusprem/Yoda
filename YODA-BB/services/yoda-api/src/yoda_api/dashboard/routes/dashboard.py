"""Dashboard API routes for CXO executive view."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_api.config import Settings
from yoda_api.dependencies import get_db
from yoda_foundation.security.auth_dependency import get_current_user
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.data_access.repositories import MeetingRepository, ActionItemRepository
from yoda_foundation.models.document import Document
from yoda_foundation.models.summary import MeetingSummary
from yoda_foundation.models.action_item import ActionItem
from yoda_foundation.models.meeting import Meeting, MeetingParticipant

_logger = logging.getLogger(__name__)

router = APIRouter()


class M365StatusResponse(BaseModel):
    """Response schema for the M365 connectivity check."""

    connected: bool
    details: str


@router.get("/m365-status", response_model=M365StatusResponse)
async def m365_status(request: Request) -> M365StatusResponse:
    """Check whether Azure / M365 credentials are configured."""
    try:
        settings: Settings = getattr(request.app.state, "settings", None) or Settings()

        tenant_ok = bool(settings.AZURE_TENANT_ID)
        client_ok = bool(settings.AZURE_CLIENT_ID)

        if tenant_ok and client_ok:
            return M365StatusResponse(
                connected=True,
                details="Azure credentials configured (tenant and client ID present)",
            )

        missing: list[str] = []
        if not tenant_ok:
            missing.append("AZURE_TENANT_ID")
        if not client_ok:
            missing.append("AZURE_CLIENT_ID")

        return M365StatusResponse(
            connected=False,
            details=f"Missing Azure credentials: {', '.join(missing)}",
        )
    except Exception as exc:
        _logger.exception("Error checking M365 status")
        return M365StatusResponse(
            connected=False,
            details=f"Error checking M365 status: {exc}",
        )


@router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db), ctx: SecurityContext = Depends(get_current_user)):
    """Return executive dashboard KPIs: meetings today, pending/overdue actions, completion rate, and docs to review.

    All statistics are scoped to the authenticated user's meetings and action items.
    """
    user_id = ctx.user_id

    # Subquery: meeting IDs the user organized or participates in
    user_meeting_ids = select(Meeting.id).where(
        or_(
            Meeting.organizer_id == user_id,
            Meeting.id.in_(
                select(MeetingParticipant.meeting_id).where(
                    MeetingParticipant.user_id == user_id
                )
            ),
        )
    )

    m_repo = MeetingRepository(db)
    a_repo = ActionItemRepository(db)
    upcoming_all = await m_repo.get_upcoming(hours=24)
    upcoming = [m for m in upcoming_all if m.organizer_id == user_id]

    overdue_all = await a_repo.get_overdue()
    overdue = [a for a in overdue_all if a.assigned_to_user_id == user_id or a.meeting_id in {m.id for m in upcoming_all if m.organizer_id == user_id}]

    pending_all = await a_repo.find_by(status="pending")
    pending = [a for a in pending_all if a.assigned_to_user_id == user_id]

    completed_all = await a_repo.find_by(status="completed")
    completed = [a for a in completed_all if a.assigned_to_user_id == user_id]

    total = len(pending) + len(completed) + len(overdue)
    rate = (len(completed) / total * 100) if total > 0 else 0

    # Docs pending review — scope to docs uploaded by the user
    docs_to_review_r = await db.execute(
        select(func.count()).select_from(Document).where(
            Document.review_status == "pending_review",
            or_(
                Document.uploaded_by == user_id,
                Document.shared_by == user_id,
            ),
        )
    )
    docs_to_review = docs_to_review_r.scalar_one()

    result = {
        "meetings_today": len(upcoming),
        "pending_actions": len(pending),
        "overdue_actions": len(overdue),
        "completion_rate": round(rate, 1),
        "docs_to_review": docs_to_review,
    }

    return result


@router.get("/attention-items")
async def get_attention_items(db: AsyncSession = Depends(get_db), ctx: SecurityContext = Depends(get_current_user)):
    """Return items needing attention: overdue and due-soon action items.

    Scoped to action items assigned to or organized by the authenticated user.
    """
    user_id = ctx.user_id
    a_repo = ActionItemRepository(db)
    overdue_all = await a_repo.get_overdue()
    due_soon_all = await a_repo.get_due_soon(hours=48)

    # Scope to items the user is assigned to
    overdue = [a for a in overdue_all if a.assigned_to_user_id == user_id]
    due_soon = [a for a in due_soon_all if a.assigned_to_user_id == user_id]

    items = [{"type": "overdue", "description": a.description, "deadline": str(a.deadline), "meeting_id": str(a.meeting_id)} for a in overdue[:5]]
    items += [{"type": "due_soon", "description": a.description, "deadline": str(a.deadline), "meeting_id": str(a.meeting_id)} for a in due_soon[:5]]
    return {"items": items, "total": len(items)}


@router.get("/activity-feed")
async def get_activity_feed(
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Extended activity feed with summaries, action items, and document uploads.

    Scoped to the authenticated user's meetings, action items, and documents.
    """
    user_id = ctx.user_id
    feed: list[dict] = []

    # Subquery: meeting IDs the user organized or participates in
    user_meeting_ids = select(Meeting.id).where(
        or_(
            Meeting.organizer_id == user_id,
            Meeting.id.in_(
                select(MeetingParticipant.meeting_id).where(
                    MeetingParticipant.user_id == user_id
                )
            ),
        )
    )

    # Completed meetings with summaries (summary_ready) — scoped to user's meetings
    summary_result = await db.execute(
        select(MeetingSummary)
        .join(Meeting, MeetingSummary.meeting_id == Meeting.id)
        .where(MeetingSummary.meeting_id.in_(user_meeting_ids))
        .order_by(MeetingSummary.created_at.desc())
        .limit(limit)
    )
    for s in summary_result.scalars().all():
        feed.append({
            "type": "summary_ready",
            "title": "Summary ready for meeting",
            "meeting_id": str(s.meeting_id),
            "timestamp": str(s.created_at),
        })

    # Recently assigned action items (action_assigned) — scoped to user
    action_result = await db.execute(
        select(ActionItem)
        .where(
            ActionItem.status == "pending",
            or_(
                ActionItem.assigned_to_user_id == user_id,
                ActionItem.meeting_id.in_(user_meeting_ids),
            ),
        )
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

    # Recent document uploads (document_shared) — scoped to user's docs
    doc_result = await db.execute(
        select(Document)
        .where(
            or_(
                Document.uploaded_by == user_id,
                Document.shared_by == user_id,
                Document.meeting_id.in_(user_meeting_ids),
            ),
        )
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


@router.get("/recommendations")
async def get_recommendations(
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> dict:
    """AI-powered recommendations for the user.

    Rule-based engine that generates recommendations:
    1. Overdue cluster -- 3+ overdue action items for the same person.
    2. Stale 1:1 -- contacts not met in 14+ days.
    3. Unresolved topic -- recurring topic in 4+ meetings without a decision.
    """
    recommendations: list[dict] = []

    # Rule 1: Overdue clusters -- 3+ overdue items for the same person
    now = datetime.now(UTC)
    overdue_result = await db.execute(
        select(ActionItem.assigned_to_name, func.count(ActionItem.id))
        .where(
            ActionItem.status == "pending",
            ActionItem.deadline.isnot(None),
            ActionItem.deadline < now,
        )
        .group_by(ActionItem.assigned_to_name)
        .having(func.count(ActionItem.id) >= 3)
    )
    for name, count in overdue_result.all():
        recommendations.append({
            "type": "overdue_cluster",
            "title": f"{name} has {count} overdue items",
            "description": f"Consider a check-in with {name} to unblock progress.",
            "priority": "high",
        })

    # Rule 2: Stale 1:1 -- contacts not met in 14+ days
    fourteen_days_ago = now - timedelta(days=14)
    contacts_result = await db.execute(
        select(
            MeetingParticipant.user_id,
            MeetingParticipant.display_name,
            func.max(Meeting.scheduled_start).label("last_meeting"),
        )
        .join(Meeting, MeetingParticipant.meeting_id == Meeting.id)
        .where(
            MeetingParticipant.user_id.isnot(None),
            Meeting.status == "completed",
        )
        .group_by(MeetingParticipant.user_id, MeetingParticipant.display_name)
    )
    for row in contacts_result.all():
        if row.last_meeting < fourteen_days_ago:
            days_since = (now - row.last_meeting).days
            recommendations.append({
                "type": "stale_one_on_one",
                "title": f"No meeting with {row.display_name} in {days_since} days",
                "description": f"Schedule a catch-up with {row.display_name}.",
                "priority": "medium",
            })

    # Rule 3: Unresolved topic -- recurring topic in 4+ meetings without a decision
    from yoda_api.dashboard.services.topic_detection_service import RecurringTopicService

    topic_svc = RecurringTopicService()
    recurring = await topic_svc.detect_recurring_topics(db, days=30)
    for topic_info in recurring:
        if topic_info["meeting_count"] >= 4:
            recommendations.append({
                "type": "unresolved_topic",
                "title": f"'{topic_info['topic']}' discussed in {topic_info['meeting_count']} meetings",
                "description": "This topic keeps coming up without a clear decision. Consider scheduling a focused session.",
                "priority": "medium",
            })

    return {"recommendations": recommendations, "total": len(recommendations)}
