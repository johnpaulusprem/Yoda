"""ACS Call Automation event handler.

Receives and dispatches ACS CloudEvent callbacks (CallConnected,
CallDisconnected, ParticipantsUpdated, etc.).  This service does NOT
make outbound calls — the C# Media Bot handles all call-making.
Post-processing is delegated to PostProcessingService.

Spec reference: Section 6.4
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import Meeting, MeetingParticipant
from app.schemas.acs import ACSCallEvent

if TYPE_CHECKING:
    from app.services.post_processing import PostProcessingService

logger = logging.getLogger(__name__)


class ACSCallService:
    """Handles incoming ACS Call Automation CloudEvent callbacks.

    This is a *receiver* — it processes events that ACS sends to us,
    but never initiates calls.  Call-making is done by the C# Media Bot
    via BotCommander.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.post_processing: PostProcessingService | None = None

    # ------------------------------------------------------------------
    # Callback event dispatcher
    # ------------------------------------------------------------------

    async def handle_callback(self, event: dict | ACSCallEvent) -> None:
        """Route an ACS Call Automation CloudEvent to the appropriate handler."""
        if isinstance(event, dict):
            parsed = ACSCallEvent.model_validate(event)
        else:
            parsed = event

        event_name = parsed.event_name
        call_connection_id = parsed.call_connection_id

        logger.info(
            "ACS callback: event=%s  call_connection_id=%s",
            event_name,
            call_connection_id,
        )

        handler = {
            "CallConnected": self._on_call_connected,
            "CallDisconnected": self._on_call_disconnected,
            "ParticipantsUpdated": self._on_participants_updated,
            "TranscriptionStarted": self._on_transcription_started,
            "TranscriptionStopped": self._on_transcription_stopped,
            "MediaStreamingStarted": self._on_media_streaming_started,
            "MediaStreamingStopped": self._on_media_streaming_stopped,
            "PlayCompleted": self._on_play_completed,
            "PlayFailed": self._on_play_failed,
        }.get(event_name)

        if handler is not None:
            await handler(parsed)
        else:
            logger.warning("Unhandled ACS event type: %s", event_name)

    # ------------------------------------------------------------------
    # Individual event handlers
    # ------------------------------------------------------------------

    async def _on_call_connected(self, event: ACSCallEvent) -> None:
        """Bot successfully joined the meeting."""
        meeting = await self._meeting_by_call_connection(event.call_connection_id)
        if meeting is None:
            logger.warning(
                "CallConnected for unknown call_connection_id=%s",
                event.call_connection_id,
            )
            return

        logger.info(
            "Bot connected to meeting %s (%s)",
            meeting.id,
            meeting.subject,
        )

        if meeting.status != "in_progress":
            meeting.status = "in_progress"
            meeting.actual_start = meeting.actual_start or datetime.now(timezone.utc)
            self.db.add(meeting)
            await self.db.commit()

    async def _on_call_disconnected(self, event: ACSCallEvent) -> None:
        """Meeting ended or bot was removed.

        1. Mark meeting as completed, record actual_end.
        2. Fire the post-processing pipeline as a background task.
        """
        meeting = await self._meeting_by_call_connection(event.call_connection_id)
        if meeting is None:
            logger.warning(
                "CallDisconnected for unknown call_connection_id=%s",
                event.call_connection_id,
            )
            return

        logger.info(
            "Bot disconnected from meeting %s (%s)",
            meeting.id,
            meeting.subject,
        )

        meeting.status = "completed"
        meeting.actual_end = datetime.now(timezone.utc)
        self.db.add(meeting)
        await self.db.commit()
        await self.db.refresh(meeting)

        if self.post_processing is not None:
            asyncio.create_task(self.post_processing.run(meeting.id))

    async def _on_participants_updated(self, event: ACSCallEvent) -> None:
        """Someone joined or left — update the participant roster."""
        meeting = await self._meeting_by_call_connection(event.call_connection_id)
        if meeting is None:
            return

        if event.data.participants is None:
            return

        now = datetime.now(timezone.utc)

        for p in event.data.participants:
            raw_id = p.raw_id or ""
            display_name = p.display_name or "Unknown"

            stmt = select(MeetingParticipant).where(
                MeetingParticipant.meeting_id == meeting.id,
                MeetingParticipant.user_id == raw_id,
            )
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing is None:
                participant = MeetingParticipant(
                    meeting_id=meeting.id,
                    user_id=raw_id,
                    display_name=display_name,
                    role="attendee",
                    joined_at=now,
                )
                self.db.add(participant)
            else:
                if existing.display_name == "Unknown" and display_name != "Unknown":
                    existing.display_name = display_name
                    self.db.add(existing)

        count_stmt = select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting.id
        )
        count_result = await self.db.execute(count_stmt)
        meeting.participant_count = len(count_result.scalars().all())
        self.db.add(meeting)
        await self.db.commit()

        logger.info(
            "Participants updated for meeting %s, count=%d",
            meeting.id,
            meeting.participant_count,
        )

    async def _on_transcription_started(self, event: ACSCallEvent) -> None:
        logger.info(
            "Transcription started for call_connection_id=%s",
            event.call_connection_id,
        )

    async def _on_transcription_stopped(self, event: ACSCallEvent) -> None:
        logger.info(
            "Transcription stopped for call_connection_id=%s",
            event.call_connection_id,
        )

    async def _on_media_streaming_started(self, event: ACSCallEvent) -> None:
        logger.info(
            "Media streaming started for call_connection_id=%s",
            event.call_connection_id,
        )

    async def _on_media_streaming_stopped(self, event: ACSCallEvent) -> None:
        logger.info(
            "Media streaming stopped for call_connection_id=%s",
            event.call_connection_id,
        )

    async def _on_play_completed(self, event: ACSCallEvent) -> None:
        logger.info(
            "Play completed for call_connection_id=%s",
            event.call_connection_id,
        )

    async def _on_play_failed(self, event: ACSCallEvent) -> None:
        logger.warning(
            "Play failed for call_connection_id=%s  result=%s",
            event.call_connection_id,
            event.data.result_information,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _meeting_by_call_connection(
        self, call_connection_id: str | None
    ) -> Meeting | None:
        """Look up a meeting by its call connection ID."""
        if not call_connection_id:
            return None
        stmt = select(Meeting).where(
            Meeting.acs_call_connection_id == call_connection_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
