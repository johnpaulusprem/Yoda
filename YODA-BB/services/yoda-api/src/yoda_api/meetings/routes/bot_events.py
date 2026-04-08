"""Bot events route — receives transcript chunks and lifecycle events from Browser Bot."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_api.config import Settings
from yoda_api.dependencies import get_db
from yoda_api.meetings.routes.sse import publish_meeting_event
from yoda_foundation.models.meeting import Meeting, MeetingParticipant
from yoda_foundation.models.transcript import SpeakerEvent, TranscriptSegment
from yoda_api.meetings.schemas.bot_events import BotLifecycleEventIn, SpeakerEventIn, TranscriptChunkIn
from yoda_api.meetings.utils.hmac_auth import validate_hmac

logger = logging.getLogger(__name__)
router = APIRouter()

# Valid status transitions — prevents race conditions where late events
# overwrite terminal states.
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"joining", "in_progress", "failed", "cancelled"},
    "joining": {"in_progress", "completed", "error", "failed"},
    "in_progress": {"completed", "error"},
    "completed": {"processing_failed"},  # allow post-processing failure
    "failed": set(),  # terminal
    "error": {"in_progress"},  # allow recovery
    "cancelled": set(),  # terminal
    "processing_failed": set(),  # terminal — needs manual reprocessing
}


def _can_transition(current: str, target: str) -> bool:
    return target in _VALID_TRANSITIONS.get(current, set())


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/transcript")
async def ingest_transcript(
    payload: TranscriptChunkIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive batched transcript segments from the Browser Bot.

    Uses savepoints with IntegrityError catch to deduplicate retransmitted
    batches (works with both PostgreSQL and SQLite).
    """
    settings = _get_settings(request)
    await validate_hmac(request, settings)

    meeting_uuid = uuid.UUID(payload.meeting_id)  # validated by schema

    count = 0
    try:
        for seg in payload.segments:
            if not seg.is_final:
                continue

            # Use savepoint per segment to skip duplicates (works with both
            # PostgreSQL and SQLite — UniqueConstraint on meeting_id + sequence_number).
            try:
                async with db.begin_nested():
                    db.add(
                        TranscriptSegment(
                            meeting_id=meeting_uuid,
                            speaker_name=seg.speaker_name,
                            speaker_id=seg.speaker_id or None,
                            text=seg.text,
                            start_time=seg.start_time_sec,
                            end_time=seg.end_time_sec,
                            confidence=seg.confidence,
                            sequence_number=seg.sequence,
                            source=seg.source,
                        )
                    )
                count += 1
            except IntegrityError:
                # Duplicate (meeting_id, sequence_number) — skip silently
                pass

        if count > 0:
            await db.commit()
    except SQLAlchemyError:
        logger.exception(
            "Database error ingesting transcript",
            extra={"meeting_id": payload.meeting_id, "segment_count": len(payload.segments)},
        )
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error")

    # Push ingested segments to connected SSE clients for real-time updates
    if count > 0:
        publish_meeting_event(
            payload.meeting_id,
            {
                "type": "transcript_update",
                "meeting_id": payload.meeting_id,
                "segment_count": count,
                "segments": [
                    {
                        "speaker_name": seg.speaker_name,
                        "text": seg.text,
                        "start_time_sec": seg.start_time_sec,
                        "end_time_sec": seg.end_time_sec,
                        "sequence": seg.sequence,
                    }
                    for seg in payload.segments
                    if seg.is_final
                ],
            },
        )

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
    """Handle lifecycle events from the Browser Bot."""
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
            await _handle_bot_error(db, meeting, payload)

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
    if not _can_transition(meeting.status, "in_progress"):
        logger.warning(
            "Ignoring bot_joined: invalid transition from %s to in_progress",
            meeting.status,
            extra={"meeting_id": str(meeting.id)},
        )
        return
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
    if not _can_transition(meeting.status, "completed"):
        logger.warning(
            "Ignoring meeting_ended: invalid transition from %s to completed",
            meeting.status,
            extra={"meeting_id": str(meeting.id)},
        )
        return

    meeting.status = "completed"
    meeting.actual_end = datetime.now(timezone.utc)
    await db.commit()

    # Trigger post-processing as a background task with error handling
    post_processing = getattr(request.app.state, "post_processing", None)
    if post_processing is not None:
        task = asyncio.create_task(
            _post_process_with_retry(post_processing, meeting.id),
            name=f"post_processing_{meeting.id}",
        )
        task.add_done_callback(_log_task_exception)
    else:
        logger.warning(
            "Post-processing not available — post_processing service not configured",
            extra={"meeting_id": str(meeting.id)},
        )

    logger.info(
        "Meeting ended, post-processing triggered",
        extra={"meeting_id": str(meeting.id)},
    )


async def _post_process_with_retry(post_processing: object, meeting_id: uuid.UUID) -> None:
    """Run post-processing with retry. On final failure, mark meeting as needing reprocessing."""
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            await post_processing.run(meeting_id)  # type: ignore[attr-defined]
            return
        except Exception:
            if attempt == max_retries:
                logger.error(
                    "Post-processing failed after %d attempts for meeting %s — "
                    "meeting needs manual reprocessing",
                    max_retries + 1,
                    meeting_id,
                )
                # Update meeting status to indicate processing failed
                from yoda_api.dependencies import get_session_factory
                async_session_factory = get_session_factory()

                try:
                    async with async_session_factory() as db:
                        result = await db.execute(
                            select(Meeting).where(Meeting.id == meeting_id)
                        )
                        m = result.scalar_one_or_none()
                        if m and _can_transition(m.status, "processing_failed"):
                            m.status = "processing_failed"
                            await db.commit()
                except Exception:
                    logger.exception(
                        "Failed to update meeting status to processing_failed"
                    )
                raise
            logger.warning(
                "Post-processing attempt %d failed for meeting %s, retrying...",
                attempt + 1,
                meeting_id,
                exc_info=True,
            )
            await asyncio.sleep(5 * (attempt + 1))


async def _handle_bot_error(
    db: AsyncSession, meeting: Meeting, payload: BotLifecycleEventIn
) -> None:
    """Handle bot error — only transition if status allows it."""
    if not _can_transition(meeting.status, "error"):
        logger.warning(
            "Ignoring bot_error: invalid transition from %s to error",
            meeting.status,
            extra={"meeting_id": str(meeting.id)},
        )
        return

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


async def _handle_participants_updated(
    db: AsyncSession, meeting: Meeting, payload: BotLifecycleEventIn
) -> None:
    """Add new participants to the meeting (batch query, no N+1)."""
    raw_participants = (payload.data or {}).get("participants", [])
    now = datetime.now(timezone.utc)

    # Validate participant entries — skip malformed ones instead of crashing
    participants: list[dict] = []
    for p in raw_participants:
        if not isinstance(p, dict):
            logger.warning(
                "Skipping malformed participant entry: %s",
                type(p).__name__,
                extra={"meeting_id": str(meeting.id)},
            )
            continue
        participants.append(p)

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
        if not isinstance(user_id, str) or not user_id:
            continue
        if user_id in existing_ids:
            continue
        display_name = p.get("displayName", "Unknown")
        if not isinstance(display_name, str):
            display_name = "Unknown"
        db.add(
            MeetingParticipant(
                meeting_id=meeting.id,
                user_id=user_id,
                display_name=display_name,
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


# ── Speaker Events ──────────────────────────────────────────────────


@router.post("/speaker")
async def ingest_speaker_event(
    request: Request,
    payload: SpeakerEventIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive SPEAKER_START/SPEAKER_END events from the browser bot.

    These are used for overlap-based speaker attribution when the
    transcription service cannot determine the speaker from audio alone.
    """
    settings: Settings = request.app.state.settings
    await validate_hmac(request, settings)

    meeting_id = uuid.UUID(payload.meeting_id)

    event = SpeakerEvent(
        meeting_id=meeting_id,
        bot_instance_id=payload.bot_instance_id,
        event_type=payload.event_type,
        participant_id=payload.participant_id,
        participant_name=payload.participant_name,
        relative_timestamp_ms=payload.relative_timestamp_ms,
    )
    db.add(event)

    logger.debug(
        "Speaker event: %s %s at %.0fms",
        payload.event_type,
        payload.participant_name or payload.participant_id,
        payload.relative_timestamp_ms,
        extra={"meeting_id": str(meeting_id)},
    )

    return {"status": "ok"}
