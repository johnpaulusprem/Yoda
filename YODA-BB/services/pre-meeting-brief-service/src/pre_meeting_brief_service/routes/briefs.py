"""Pre-meeting brief API routes."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pre_meeting_brief_service.dependencies import get_db
from pre_meeting_brief_service.schemas import PreMeetingBriefResponse
from pre_meeting_brief_service.services.pre_meeting_service import PreMeetingService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/briefs/{meeting_id}", response_model=PreMeetingBriefResponse)
async def get_brief(
    request: Request,
    meeting_id: UUID,
    user_id: str = Query(..., description="Azure AD user ID of the executive"),
    db: AsyncSession = Depends(get_db),
):
    """Generate a pre-meeting brief for the specified meeting.

    Gathers attendee context, past decisions, related documents,
    recent emails, and AI-suggested questions.
    """
    graph_client = getattr(request.app.state, "graph_client", None)
    ai_connector = getattr(request.app.state, "ai_connector", None)
    cache = getattr(request.app.state, "cache", None)

    service = PreMeetingService(
        db=db,
        graph_client=graph_client,
        ai_connector=ai_connector,
        cache=cache,
    )

    brief = await service.generate_brief(meeting_id=meeting_id, user_id=user_id)

    return PreMeetingBriefResponse(
        meeting_id=brief.meeting_id,
        meeting_subject=brief.meeting_subject,
        scheduled_start=brief.scheduled_start,
        attendees=[
            {
                "user_id": a.user_id,
                "display_name": a.display_name,
                "email": a.email,
                "role": a.role,
                "job_title": a.job_title,
                "department": a.department,
                "recent_interactions": a.recent_interactions,
                "overdue_action_items": a.overdue_action_items,
                "last_meeting_subject": a.last_meeting_subject,
            }
            for a in brief.attendees
        ],
        past_decisions=[
            {
                "decision_text": d.decision_text,
                "meeting_subject": d.meeting_subject,
                "meeting_date": d.meeting_date,
                "context": d.context,
            }
            for d in brief.past_decisions
        ],
        related_documents=[
            {
                "title": doc.title,
                "source": doc.source,
                "source_url": doc.source_url,
                "relevance_reason": doc.relevance_reason,
            }
            for doc in brief.related_documents
        ],
        recent_email_subjects=brief.recent_email_subjects,
        recent_email_threads=[
            {
                "subject": t.subject,
                "sender_name": t.sender_name,
                "sender_email": t.sender_email,
                "snippet": t.snippet,
                "received_at": t.received_at,
            }
            for t in brief.recent_email_threads
        ],
        suggested_questions=brief.suggested_questions,
        executive_summary=brief.executive_summary,
        generated_at=brief.generated_at,
    )
