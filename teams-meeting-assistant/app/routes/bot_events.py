"""Bot events route — receives transcript chunks and lifecycle events from C# Media Bot."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.dependencies import get_db
from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.schemas.bot_events import BotLifecycleEventIn, TranscriptChunkIn
from app.utils.hmac_auth import validate_hmac

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/transcript")
async def ingest_transcript(
    payload: TranscriptChunkIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive batched transcript segments from the C# Media Bot."""
    settings = _get_settings(request)
    await validate_hmac(request, settings)

    meeting_uuid = uuid.UUID(payload.meeting_id)  # validated by schema

    count = 0
    try:
        for seg in payload.segments:
            if not seg.is_final:
                continue
            segment = TranscriptSegment(
                meeting_id=meeting_uuid,
                speaker_name=seg.speaker_name,
                speaker_id=seg.speaker_id or None,
                text=seg.text,
                start_time=seg.start_time_sec,
                end_time=seg.end_time_sec,
                confidence=seg.confidence,
                sequence_number=seg.sequence,
            )
            db.add(segment)
            count += 1

        if count > 0:
            await db.commit()
    except SQLAlchemyError:
        logger.exception(
            "Database error ingesting transcript",
            extra={"meeting_id": payload.meeting_id, "segment_count": len(payload.segments)},
        )
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error")

    logger.info(
        "Ingested transcript segments",
        extra={
            "meeting_id": payload.meeting_id,
            "received": count,
            "total_segments": len(payload.segments),
            "bot_instance_id": payload.bot_instance_id,
        },
    )
    return {"received": count}


@router.post("/lifecycle")
async def handle_lifecycle(
    payload: BotLifecycleEventIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Handle lifecycle events from the C# Media Bot."""
    settings = _get_settings(request)
    await validate_hmac(request, settings)

    meeting_uuid = uuid.UUID(payload.meeting_id)  # validated by schema

    try:
        result = await db.execute(
            select(Meeting).where(Meeting.id == meeting_uuid)
        )
        meeting = result.scalar_one_or_none()
    except SQLAlchemyError:
        logger.exception(
            "Database error looking up meeting",
            extra={"meeting_id": payload.meeting_id},
        )
        raise HTTPException(status_code=500, detail="Database error")

    if meeting is None:
        logger.warning(
            "Lifecycle event for unknown meeting",
            extra={
                "meeting_id": payload.meeting_id,
                "event_type": payload.event_type,
            },
        )
        return {"status": "meeting_not_found"}

    try:
        if payload.event_type == "bot_joined":
            await _handle_bot_joined(db, meeting)

        elif payload.event_type == "meeting_ended":
            await _handle_meeting_ended(db, meeting, request)

        elif payload.event_type == "participants_updated":
            await _handle_participants_updated(db, meeting, payload)

        elif payload.event_type == "bot_error":
            meeting.status = "error"
            await db.commit()
            logger.error(
                "Bot error reported",
                extra={
                    "meeting_id": str(meeting.id),
                    "error_data": payload.data,
                    "bot_instance_id": payload.bot_instance_id,
                },
            )
    except SQLAlchemyError:
        logger.exception(
            "Database error handling lifecycle event",
            extra={
                "meeting_id": payload.meeting_id,
                "event_type": payload.event_type,
            },
        )
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error")

    return {"status": "ok"}


async def _handle_bot_joined(db: AsyncSession, meeting: Meeting) -> None:
    """Mark meeting as in_progress when bot joins."""
    if meeting.status != "in_progress":
        meeting.status = "in_progress"
        meeting.actual_start = meeting.actual_start or datetime.now(timezone.utc)
        await db.commit()
    logger.info(
        "Bot joined meeting",
        extra={"meeting_id": str(meeting.id), "status": meeting.status},
    )


async def _handle_meeting_ended(
    db: AsyncSession, meeting: Meeting, request: Request
) -> None:
    """Mark meeting completed and trigger post-processing pipeline."""
    meeting.status = "completed"
    meeting.actual_end = datetime.now(timezone.utc)
    await db.commit()

    # Trigger post-processing as a background task with error handling
    acs_service = getattr(request.app.state, "acs_service", None)
    if acs_service and hasattr(acs_service, "_run_post_processing"):
        task = asyncio.create_task(
            acs_service._run_post_processing(meeting.id),
            name=f"post_processing_{meeting.id}",
        )
        task.add_done_callback(_log_task_exception)

    logger.info(
        "Meeting ended, post-processing triggered",
        extra={"meeting_id": str(meeting.id)},
    )


async def _handle_participants_updated(
    db: AsyncSession, meeting: Meeting, payload: BotLifecycleEventIn
) -> None:
    """Add new participants to the meeting (batch query, no N+1)."""
    participants = (payload.data or {}).get("participants", [])
    now = datetime.now(timezone.utc)

    # Single query to get all existing participant user_ids for this meeting
    existing_result = await db.execute(
        select(MeetingParticipant.user_id).where(
            MeetingParticipant.meeting_id == meeting.id,
        )
    )
    existing_ids = set(existing_result.scalars().all())

    added = 0
    for p in participants:
        user_id = p.get("id", "")
        if not user_id or user_id in existing_ids:
            continue
        db.add(
            MeetingParticipant(
                meeting_id=meeting.id,
                user_id=user_id,
                display_name=p.get("displayName", "Unknown"),
                role="attendee",
                joined_at=now,
            )
        )
        existing_ids.add(user_id)
        added += 1

    # Use COUNT instead of loading all rows
    count_result = await db.execute(
        select(func.count())
        .select_from(MeetingParticipant)
        .where(MeetingParticipant.meeting_id == meeting.id)
    )
    meeting.participant_count = count_result.scalar_one()
    await db.commit()

    logger.info(
        "Participants updated",
        extra={
            "meeting_id": str(meeting.id),
            "new_participants": added,
            "total_participants": meeting.participant_count,
        },
    )


def _log_task_exception(task: asyncio.Task) -> None:
    """Callback to log unhandled exceptions from background tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Post-processing task failed: %s",
            exc,
            extra={"task_name": task.get_name()},
            exc_info=exc,
        )
