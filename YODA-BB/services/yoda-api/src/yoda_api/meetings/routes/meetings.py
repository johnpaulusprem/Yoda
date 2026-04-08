"""Meeting API routes for the UI dashboard.

Provides read-only access to meetings and transcripts, plus the ability
to re-trigger AI processing on an existing transcript.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yoda_api.dependencies import get_db
from yoda_foundation.models.action_item import ActionItem
from yoda_foundation.models.meeting import Meeting, MeetingParticipant
from yoda_foundation.models.summary import MeetingSummary
from yoda_foundation.models.transcript import TranscriptSegment
from yoda_foundation.schemas.meeting import (
    CreateMeetingRequest,
    MeetingDetailResponse,
    MeetingListResponse,
    MeetingResponse,
    MeetingWithTagsResponse,
    _extract_thread_id_from_join_url,
)
from yoda_foundation.schemas.summary import SummaryResponse, SummaryUpdateRequest
from yoda_foundation.schemas.transcript import TranscriptResponse
from yoda_api.meetings.services.meeting_tag_service import compute_tags
from yoda_api.meetings.utils.azure_ad_auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health/browser-bot")
async def check_browser_bot() -> dict:
    """Check if the Browser Bot is reachable."""
    from yoda_api.meetings.services.bot_commander import get_shared_bot_commander, BotCommander
    from yoda_api.config import Settings

    bot = get_shared_bot_commander()
    owns_bot = False

    if bot is None:
        bot = BotCommander(settings=Settings())
        owns_bot = True

    try:
        capacity = await bot.get_capacity()
        logger.info("Browser Bot is reachable", extra={"capacity": capacity})
        return {"status": "ok", "browser_bot_url": bot.base_url, "capacity": capacity}
    except Exception as exc:
        logger.error("Browser Bot is NOT reachable: %s", exc)
        return {"status": "unreachable", "browser_bot_url": bot.base_url, "error": "Connection failed"}
    finally:
        if owns_bot:
            await bot.close()



@router.post("", response_model=MeetingResponse, status_code=201)
async def create_meeting(
    body: CreateMeetingRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> MeetingResponse:
    """Create a meeting for testing bot join + transcription.

    Use this to create a meeting record with a Teams join URL, then call
    POST /api/meetings/{meeting_id}/join to trigger the bot. Transcript will
    appear at GET /api/meetings/{meeting_id}/transcript (Browser Bot path).
    """
    now = datetime.now(timezone.utc)
    start = now
    end = now + timedelta(hours=1)
    meeting_id = uuid_mod.uuid4()
    thread_id = _extract_thread_id_from_join_url(body.join_url)
    # Use a stable fake ID for teams_meeting_id so we can look up by join_url if needed
    teams_meeting_id = f"test-{meeting_id.hex[:12]}"

    meeting = Meeting(
        id=meeting_id,
        teams_meeting_id=teams_meeting_id,
        thread_id=thread_id,
        join_url=body.join_url,
        subject=body.subject,
        organizer_id=_user.get("sub", "test-organizer"),
        organizer_name=body.organizer_name,
        organizer_email=body.organizer_email,
        scheduled_start=start,
        scheduled_end=end,
        status="scheduled",
    )
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    logger.info(
        "Created test meeting",
        extra={"meeting_id": str(meeting_id), "subject": body.subject},
    )
    return MeetingResponse.model_validate(meeting)


@router.get("", response_model=MeetingListResponse)
async def list_meetings(
    status: str | None = Query(
        None,
        description="Filter by meeting status: scheduled, in_progress, completed, failed, cancelled",
    ),
    limit: int = Query(20, ge=1, le=100, description="Max number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> MeetingListResponse:
    """List meetings with optional status filter and limit/offset pagination.

    Returns a paginated list of meetings ordered by scheduled start time
    (most recent first).  Results are scoped to meetings the authenticated
    user organized or participates in.
    """
    user_id = _user.get("sub", "")

    # Build the base query
    base_query = select(Meeting)
    count_query = select(func.count()).select_from(Meeting)

    if status is not None:
        valid_statuses = {"scheduled", "in_progress", "completed", "failed", "cancelled"}
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}",
            )
        base_query = base_query.where(Meeting.status == status)
        count_query = count_query.where(Meeting.status == status)

    # Scope to meetings the user organized or participates in
    user_scope = or_(
        Meeting.organizer_id == user_id,
        Meeting.id.in_(
            select(MeetingParticipant.meeting_id).where(
                MeetingParticipant.user_id == user_id
            )
        ),
    )
    base_query = base_query.where(user_scope)
    count_query = count_query.where(user_scope)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Fetch paginated results with participants eager-loaded for tag computation
    query = (
        base_query
        .options(selectinload(Meeting.participants))
        .order_by(Meeting.scheduled_start.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    meetings = result.scalars().all()

    if not meetings:
        return MeetingListResponse(items=[], total=total)

    # Batch-load action items and summaries for tag computation (avoids N+1)
    meeting_ids = [m.id for m in meetings]

    action_items_result = await db.execute(
        select(ActionItem).where(ActionItem.meeting_id.in_(meeting_ids))
    )
    all_action_items = action_items_result.scalars().all()
    action_items_by_meeting: dict[UUID, list[ActionItem]] = {}
    for ai in all_action_items:
        action_items_by_meeting.setdefault(ai.meeting_id, []).append(ai)

    summaries_result = await db.execute(
        select(MeetingSummary).where(MeetingSummary.meeting_id.in_(meeting_ids))
    )
    all_summaries = summaries_result.scalars().all()
    summary_by_meeting = {s.meeting_id: s for s in all_summaries}

    # Build tagged response items
    items: list[MeetingWithTagsResponse] = []
    for m in meetings:
        m_items = action_items_by_meeting.get(m.id, [])
        m_summary = summary_by_meeting.get(m.id)
        tags = compute_tags(
            m,
            action_items=m_items,
            has_brief=False,
            summary=m_summary,
        )
        resp = MeetingWithTagsResponse.model_validate(m)
        resp.tags = tags
        items.append(resp)

    return MeetingListResponse(items=items, total=total)


@router.get("/{meeting_id}", response_model=MeetingDetailResponse)
async def get_meeting(
    meeting_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> MeetingDetailResponse:
    """Get full meeting details including summary, action items, and participants."""
    query = (
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .options(
            selectinload(Meeting.summary),
            selectinload(Meeting.action_items),
            selectinload(Meeting.participants),
        )
    )
    result = await db.execute(query)
    meeting = result.scalar_one_or_none()

    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return MeetingDetailResponse.model_validate(meeting)


@router.get("/{meeting_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    meeting_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> TranscriptResponse:
    """Get all transcript segments for a meeting, ordered by sequence number."""
    # First, verify the meeting exists
    meeting_query = select(Meeting.id).where(Meeting.id == meeting_id)
    meeting_result = await db.execute(meeting_query)
    if meeting_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Fetch transcript segments ordered by sequence_number
    segments_query = (
        select(TranscriptSegment)
        .where(TranscriptSegment.meeting_id == meeting_id)
        .order_by(TranscriptSegment.sequence_number)
    )
    result = await db.execute(segments_query)
    segments = result.scalars().all()

    # Get total count
    count_query = (
        select(func.count())
        .select_from(TranscriptSegment)
        .where(TranscriptSegment.meeting_id == meeting_id)
    )
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    return TranscriptResponse(
        segments=[
            {
                "id": s.id,
                "meeting_id": s.meeting_id,
                "speaker_name": s.speaker_name,
                "speaker_id": s.speaker_id,
                "text": s.text,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "confidence": s.confidence,
                "sequence_number": s.sequence_number,
            }
            for s in segments
        ],
        total=total,
    )


@router.post("/{meeting_id}/join")
async def join_meeting(
    meeting_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> dict:
    """Trigger the Browser Bot to join a Teams meeting.

    Called by the React app when a user clicks "Join" or automatically
    by the calendar watcher before a meeting starts.

    The meeting must be in 'scheduled' status and have a valid join_url.
    """
    query = select(Meeting).where(Meeting.id == meeting_id)
    result = await db.execute(query)
    meeting = result.scalar_one_or_none()

    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.status == "in_progress":
        return {
            "status": "already_joined",
            "meeting_id": str(meeting_id),
            "call_connection_id": meeting.acs_call_connection_id,
        }

    if meeting.status not in ("scheduled", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot join meeting with status '{meeting.status}'. "
            "Only scheduled or failed meetings can be joined.",
        )

    from yoda_api.meetings.services.bot_commander import get_shared_bot_commander, BotCommander

    bot = get_shared_bot_commander()
    owns_bot = False

    if bot is None:
        from yoda_api.config import Settings
        bot = BotCommander(settings=Settings())
        owns_bot = True

    try:
        call_id = await bot.join_meeting(
            meeting_id=str(meeting.id),
            join_url=meeting.join_url,
        )
        meeting.status = "joining"
        meeting.acs_call_connection_id = call_id
        db.add(meeting)
        await db.commit()
    except Exception as exc:
        import traceback
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        logger.exception("Failed to join meeting %s via Browser Bot", meeting_id)
        meeting.status = "failed"
        db.add(meeting)
        await db.commit()
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Failed to communicate with meeting bot",
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": tb,
            },
        ) from exc
    finally:
        if owns_bot:
            await bot.close()

    return {
        "status": "joining",
        "meeting_id": str(meeting_id),
        "call_id": call_id,
    }


@router.post("/{meeting_id}/leave")
async def leave_meeting(
    meeting_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> dict:
    """Remove the bot from an active Teams meeting.

    The meeting must be in 'in_progress' status with a valid call connection.
    """
    query = select(Meeting).where(Meeting.id == meeting_id)
    result = await db.execute(query)
    meeting = result.scalar_one_or_none()

    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.status != "in_progress":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot leave meeting with status '{meeting.status}'. "
            "Only in-progress meetings can be left.",
        )

    if not meeting.acs_call_connection_id:
        raise HTTPException(
            status_code=400,
            detail="Meeting has no active Bot call connection.",
        )

    from yoda_api.meetings.services.bot_commander import get_shared_bot_commander, BotCommander

    bot = get_shared_bot_commander()
    owns_bot = False

    if bot is None:
        from yoda_api.config import Settings
        bot = BotCommander(settings=Settings())
        owns_bot = True

    try:
        await bot.leave_meeting(meeting.acs_call_connection_id)
    except Exception as exc:
        import traceback
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        logger.exception("Failed to leave meeting %s via Browser Bot", meeting_id)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Failed to communicate with meeting bot",
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": tb,
            },
        ) from exc
    finally:
        if owns_bot:
            await bot.close()

    return {
        "status": "left",
        "meeting_id": str(meeting_id),
    }


@router.post("/{meeting_id}/reprocess")
async def reprocess_meeting(
    meeting_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> dict:
    """Re-run AI processing on an existing transcript.

    Useful when the prompt template has been updated and you want to
    regenerate the summary and action items for a past meeting.

    The meeting must have transcript segments and must be in 'completed'
    status. Any existing summary and action items are deleted before
    reprocessing.
    """
    # Load the meeting with relationships
    query = (
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .options(
            selectinload(Meeting.transcript_segments),
            selectinload(Meeting.summary),
            selectinload(Meeting.action_items),
            selectinload(Meeting.participants),
        )
    )
    result = await db.execute(query)
    meeting = result.scalar_one_or_none()

    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reprocess meeting with status '{meeting.status}'. "
            "Only completed meetings can be reprocessed.",
        )

    if not meeting.transcript_segments:
        raise HTTPException(
            status_code=400,
            detail="No transcript segments found for this meeting. "
            "Cannot reprocess without a transcript.",
        )

    # Import AI processor and related services here to avoid circular imports
    # at module level and to allow the service to be optional during testing.
    from yoda_api.meetings.services.ai_processor import AIProcessor
    from yoda_api.meetings.services.owner_resolver import OwnerResolver
    from yoda_api.config import Settings

    settings = Settings()
    ai_processor = AIProcessor(settings=settings)

    # Sort segments by sequence number for the AI processor
    sorted_segments = sorted(
        meeting.transcript_segments,
        key=lambda s: s.sequence_number,
    )

    import time

    start_time = time.monotonic()

    try:
        extraction = await ai_processor.process_meeting(
            meeting=meeting,
            transcript_segments=sorted_segments,
        )
    except Exception as exc:
        logger.exception(
            "Reprocessing failed for meeting %s", meeting_id
        )
        raise HTTPException(
            status_code=500,
            detail="AI processing failed. Please try again later.",
        ) from exc

    processing_time = time.monotonic() - start_time

    # Delete existing summary and action items
    if meeting.summary is not None:
        await db.delete(meeting.summary)
    for item in list(meeting.action_items):
        await db.delete(item)
    await db.flush()

    # Create new summary
    from yoda_foundation.models.summary import MeetingSummary
    from yoda_foundation.models.action_item import ActionItem

    new_summary = MeetingSummary(
        meeting_id=meeting.id,
        summary_text=extraction.get("summary", ""),
        decisions=extraction.get("decisions", []),
        key_topics=extraction.get("key_topics", []),
        unresolved_questions=extraction.get("unresolved_questions", []),
        model_used=extraction.get("model_used", settings.AI_FOUNDRY_DEPLOYMENT_NAME),
        processing_time_seconds=processing_time,
        delivered=False,
        delivered_at=None,
    )
    db.add(new_summary)

    # Create new action items
    new_action_items = []
    for ai_item in extraction.get("action_items", []):
        # Map confidence string to float
        _conf_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
        conf_str = ai_item.get("confidence", "medium")
        conf_val = _conf_map.get(conf_str, 0.6) if isinstance(conf_str, str) else 0.6

        action_item = ActionItem(
            meeting_id=meeting.id,
            description=ai_item.get("description", ""),
            assigned_to_name=ai_item.get("assigned_to", "Unassigned"),
            assigned_to_user_id=None,
            assigned_to_email=None,
            deadline=ai_item.get("deadline"),
            priority=ai_item.get("priority", "medium"),
            status="pending",
            source_quote=ai_item.get("source_quote"),
            confidence=conf_val,
        )
        db.add(action_item)
        new_action_items.append(action_item)

    # Attempt to resolve owners for new action items
    try:
        from yoda_foundation.utils.auth.token_provider import TokenProvider
        from yoda_api.meetings.services.graph_client import GraphClient

        token_provider = TokenProvider(
            tenant_id=settings.AZURE_TENANT_ID,
            client_id=settings.AZURE_CLIENT_ID,
            client_secret=settings.AZURE_CLIENT_SECRET,
        )
        graph_client = GraphClient(token_provider=token_provider)
        owner_resolver = OwnerResolver(graph_client=graph_client)

        for action_item in new_action_items:
            user_id, email = await owner_resolver.resolve(
                name=action_item.assigned_to_name,
                participants=list(meeting.participants),
            )
            if user_id:
                action_item.assigned_to_user_id = user_id
            if email:
                action_item.assigned_to_email = email

        await graph_client.close()
    except Exception:
        logger.warning(
            "Owner resolution failed during reprocessing; action items saved without user IDs",
            exc_info=True,
        )

    await db.commit()

    logger.info(
        "Meeting reprocessed successfully",
        extra={
            "meeting_id": str(meeting_id),
            "action_items_count": len(new_action_items),
            "processing_time_seconds": processing_time,
        },
    )

    return {
        "status": "reprocessed",
        "meeting_id": str(meeting_id),
        "summary_generated": True,
        "action_items_count": len(new_action_items),
        "processing_time_seconds": round(processing_time, 2),
    }


@router.patch("/{meeting_id}/summary", response_model=SummaryResponse)
async def edit_summary(
    meeting_id: UUID,
    body: SummaryUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> SummaryResponse:
    """Partially update a meeting's AI-generated summary.

    Only the fields provided in the request body are updated; all other
    fields remain unchanged.  Returns the full updated summary.
    """
    # Verify the meeting exists
    meeting_result = await db.execute(
        select(Meeting.id).where(Meeting.id == meeting_id)
    )
    if meeting_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Load the summary
    summary_result = await db.execute(
        select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id)
    )
    summary = summary_result.scalar_one_or_none()

    if summary is None:
        raise HTTPException(status_code=404, detail="Summary not found for this meeting")

    # Apply partial update — only set fields that were explicitly provided
    update_data = body.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="No fields to update. Provide at least one field.",
        )

    for field, value in update_data.items():
        setattr(summary, field, value)

    await db.commit()
    await db.refresh(summary)

    logger.info(
        "Updated summary for meeting %s: fields=%s",
        meeting_id,
        list(update_data.keys()),
    )

    return SummaryResponse.model_validate(summary)
