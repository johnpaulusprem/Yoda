"""Meeting API routes."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cxo_ai_companion.dependencies import get_db, get_session_factory
from cxo_ai_companion.data_access.repositories import MeetingRepository, TranscriptRepository, SummaryRepository, ActionItemRepository
from cxo_ai_companion.models.meeting import Meeting, MeetingParticipant
from cxo_ai_companion.models.summary import MeetingSummary
from cxo_ai_companion.models.action_item import ActionItem
from cxo_ai_companion.models.document import Document
from cxo_ai_companion.schemas.meeting import MeetingResponse, MeetingDetailResponse, MeetingListResponse, MeetingWithTagsResponse
from cxo_ai_companion.schemas.pre_meeting_brief import (
    AttendeeContextResponse,
    EmailThreadResponse,
    PastDecisionResponse,
    PreMeetingBriefResponse,
    RelatedDocumentResponse,
)
from cxo_ai_companion.schemas.summary import SummaryUpdateRequest, SummaryShareRequest, SummaryShareResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=MeetingListResponse)
async def list_meetings(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List meetings with optional status filter and pagination."""
    repo = MeetingRepository(db)
    if status:
        meetings = await repo.get_by_status(status, limit, offset)
    else:
        meetings = await repo.get_all(limit, offset)
    total = await repo.count(**({"status": status} if status else {}))
    return MeetingListResponse(
        items=[MeetingResponse.model_validate(m) for m in meetings], total=total
    )


@router.get("/calendar")
async def get_calendar_view(
    range: str = Query("week", description="today|week|month"),
    db: AsyncSession = Depends(get_db),
):
    """Get meetings grouped by date for calendar view with computed tags.

    Supports today/week/month ranges. Each meeting is annotated with tags
    such as brief_ready, follow_up_needed, recurring, external, high_priority,
    and decision_needed based on participants, action items, and summary state.
    """
    now = datetime.now(UTC)
    if range == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif range == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            end = start.replace(year=now.year + 1, month=1)
        else:
            end = start.replace(month=now.month + 1)
    else:  # week
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)

    result = await db.execute(
        select(Meeting)
        .where(Meeting.scheduled_start >= start, Meeting.scheduled_start < end)
        .options(
            selectinload(Meeting.participants),
            selectinload(Meeting.action_items),
            selectinload(Meeting.summary),
        )
        .order_by(Meeting.scheduled_start)
    )
    meetings = result.scalars().all()

    # Pre-fetch participant IDs with overdue actions across all meetings
    overdue_user_ids_result = await db.execute(
        select(ActionItem.assigned_to_user_id).where(
            ActionItem.status.in_(["pending", "in_progress"]),
            ActionItem.deadline.isnot(None),
            ActionItem.deadline < now,
            ActionItem.assigned_to_user_id.isnot(None),
        ).distinct()
    )
    overdue_user_ids = {row[0] for row in overdue_user_ids_result.all()}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for m in meetings:
        tags: list[str] = []
        if m.participants:
            tags.append("brief_ready")
        if any(
            a.status in ("pending", "in_progress")
            and a.deadline is not None
            and a.deadline < now
            for a in m.action_items
        ):
            tags.append("follow_up_needed")
        if getattr(m, "is_recurring", False):
            tags.append("recurring")
        # External check: participants without internal domain
        if m.participants and any(
            p.email and not p.email.endswith("@internal.com")
            for p in m.participants
        ):
            tags.append("external")
        # High priority: any attendee has overdue actions from other meetings
        participant_user_ids = {p.user_id for p in m.participants if p.user_id}
        if participant_user_ids & overdue_user_ids:
            tags.append("high_priority")
        # Decision needed: past summary has unresolved questions
        if m.summary and m.summary.unresolved_questions:
            tags.append("decision_needed")

        meeting_data = MeetingWithTagsResponse.model_validate(m)
        meeting_data.tags = tags
        date_key = m.scheduled_start.strftime("%Y-%m-%d")
        grouped[date_key].append(meeting_data.model_dump(mode="json"))

    return {"calendar": dict(grouped), "range": range}


@router.get("/{meeting_id}", response_model=MeetingDetailResponse)
async def get_meeting(meeting_id: UUID, db: AsyncSession = Depends(get_db)):
    """Retrieve a single meeting with all related details."""
    repo = MeetingRepository(db)
    meeting = await repo.get_with_details(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return MeetingDetailResponse.model_validate(meeting)


@router.get("/{meeting_id}/transcript")
async def get_transcript(meeting_id: UUID, db: AsyncSession = Depends(get_db)):
    """Retrieve transcript segments for a meeting, ordered by sequence number."""
    repo = MeetingRepository(db)
    meeting = await repo.get_by_id(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    t_repo = TranscriptRepository(db)
    segments = await t_repo.get_by_meeting(meeting_id)
    total = await t_repo.get_segment_count(meeting_id)
    return {
        "segments": [
            {
                "id": s.id, "meeting_id": s.meeting_id, "speaker_name": s.speaker_name,
                "text": s.text, "start_time": s.start_time, "end_time": s.end_time,
                "confidence": s.confidence, "sequence_number": s.sequence_number,
            }
            for s in segments
        ],
        "total": total,
    }


@router.get("/{meeting_id}/brief", response_model=PreMeetingBriefResponse)
async def get_pre_meeting_brief(
    meeting_id: UUID,
    user_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Generate a pre-meeting brief for an executive."""
    from cxo_ai_companion.services.pre_meeting_service import PreMeetingService

    service = PreMeetingService(db)
    brief = await service.generate_brief(meeting_id, user_id)

    return PreMeetingBriefResponse(
        meeting_id=brief.meeting_id,
        meeting_subject=brief.meeting_subject,
        scheduled_start=brief.scheduled_start,
        attendees=[
            AttendeeContextResponse(
                user_id=a.user_id, display_name=a.display_name, email=a.email,
                role=a.role, job_title=a.job_title, department=a.department,
                recent_interactions=a.recent_interactions,
                overdue_action_items=a.overdue_action_items,
                last_meeting_subject=a.last_meeting_subject,
            )
            for a in brief.attendees
        ],
        past_decisions=[
            PastDecisionResponse(
                decision_text=d.decision_text, meeting_subject=d.meeting_subject,
                meeting_date=d.meeting_date, context=d.context,
            )
            for d in brief.past_decisions
        ],
        related_documents=[
            RelatedDocumentResponse(
                title=d.title, source=d.source,
                source_url=d.source_url, relevance_reason=d.relevance_reason,
            )
            for d in brief.related_documents
        ],
        recent_email_subjects=brief.recent_email_subjects,
        recent_email_threads=[
            EmailThreadResponse(
                subject=t.subject, sender_name=t.sender_name,
                sender_email=t.sender_email, snippet=t.snippet,
                received_at=t.received_at,
            )
            for t in brief.recent_email_threads
        ],
        suggested_questions=brief.suggested_questions,
        executive_summary=brief.executive_summary,
        generated_at=brief.generated_at,
    )


@router.patch("/{meeting_id}/summary")
async def update_summary(
    meeting_id: UUID,
    body: SummaryUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Apply partial updates to a meeting summary (edit before sharing)."""
    repo = SummaryRepository(db)
    summary = await repo.get_by_meeting(meeting_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Summary not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(summary, field, value)
    await db.flush()
    return {"status": "updated", "meeting_id": str(meeting_id)}


@router.post("/{meeting_id}/summary/share", response_model=SummaryShareResponse)
async def share_summary(
    meeting_id: UUID,
    body: SummaryShareRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Share a meeting summary via specified channels."""
    repo = SummaryRepository(db)
    summary = await repo.get_by_meeting(meeting_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Summary not found")

    m_repo = MeetingRepository(db)
    meeting = await m_repo.get_with_details(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Attempt delivery via DeliveryService if available
    delivery_service = getattr(request.app.state, "delivery_service", None)
    if delivery_service and "chat" in body.channels:
        try:
            await delivery_service.deliver_summary(meeting, summary, meeting.action_items)
        except Exception:
            logger.warning("Delivery failed for meeting %s, marking as shared anyway", meeting_id)

    shared_at = datetime.now(UTC)
    summary.delivered = True
    summary.delivered_at = shared_at
    summary.delivery_channel = ",".join(body.channels)
    await db.flush()

    return SummaryShareResponse(
        shared=True, channels=body.channels, shared_at=shared_at
    )


@router.get("/{meeting_id}/conflicts")
async def get_conflicts(
    meeting_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Detect decision conflicts for a meeting against past meetings."""
    from cxo_ai_companion.services.conflict_detection_service import ConflictDetectionService

    service = ConflictDetectionService(get_session_factory())
    conflicts = await service.detect_conflicts(meeting_id)
    return {"meeting_id": str(meeting_id), "conflicts": conflicts, "total": len(conflicts)}


@router.post("/{meeting_id}/join")
async def join_meeting(
    meeting_id: UUID, request: Request, db: AsyncSession = Depends(get_db),
):
    """Join a scheduled meeting via ACS Call Automation.

    Validates meeting status and delegates to ACS service. Returns the
    call connection ID on success, or 502 if the ACS join fails.
    """
    repo = MeetingRepository(db)
    meeting = await repo.get_by_id(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status == "in_progress":
        return {"status": "already_joined", "meeting_id": str(meeting_id), "call_connection_id": meeting.acs_call_connection_id}
    if meeting.status not in ("scheduled", "failed"):
        raise HTTPException(status_code=400, detail=f"Cannot join meeting with status '{meeting.status}'.")
    acs_service = request.app.state.acs_service
    try:
        call_connection_id = await acs_service.join_meeting(meeting)
    except Exception as exc:
        logger.exception("Failed to join meeting %s", meeting_id)
        raise HTTPException(status_code=502, detail=f"Failed to join: {exc}") from exc
    return {"status": "joined", "meeting_id": str(meeting_id), "call_connection_id": call_connection_id}


@router.post("/{meeting_id}/leave")
async def leave_meeting(
    meeting_id: UUID, request: Request, db: AsyncSession = Depends(get_db),
):
    """Leave an in-progress meeting via ACS Call Automation."""
    repo = MeetingRepository(db)
    meeting = await repo.get_by_id(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status != "in_progress":
        raise HTTPException(status_code=400, detail=f"Cannot leave meeting with status '{meeting.status}'.")
    acs_service = request.app.state.acs_service
    try:
        await acs_service.leave_meeting(meeting.acs_call_connection_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to leave: {exc}") from exc
    return {"status": "left", "meeting_id": str(meeting_id)}
