"""ACS Call Automation service -- enterprise edition.

Joins Teams meetings, handles callback events, and orchestrates the
post-meeting processing pipeline.

Ported from ``teams-meeting-assistant/app/services/acs_call_service.py`` with:
- CXO exceptions (ACSError)
- Tracing spans via observability
- Metrics tracking (meetings_joined, meetings_failed)
- Kept join_meeting, handle_callback, leave_meeting, _run_post_processing
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from azure.communication.callautomation import (
    CallAutomationClient,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    StreamingTransportType,
    TranscriptionOptions,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cxo_ai_companion.exceptions import ACSError
from cxo_ai_companion.models.meeting import Meeting, MeetingParticipant
from cxo_ai_companion.observability import get_logger, metrics, trace_span

if TYPE_CHECKING:
    from cxo_ai_companion.services.ai_processor import AIProcessor
    from cxo_ai_companion.services.delivery import DeliveryService
    from cxo_ai_companion.services.owner_resolver import OwnerResolver

logger = get_logger("services.acs_call_service")


class ACSCallService:
    """Manages ACS Call Automation lifecycle for Teams meetings.

    Handles joining meetings via Call Automation, routing callback events
    (connect, disconnect, participant updates), and triggering the
    post-meeting AI pipeline when the call ends.

    Args:
        settings: Application settings (ACS_CONNECTION_STRING, BASE_URL).
        db: Async SQLAlchemy session for meeting state persistence.
    """

    def __init__(self, settings: Any, db: AsyncSession) -> None:
        self.client = CallAutomationClient.from_connection_string(
            settings.ACS_CONNECTION_STRING
        )
        self.settings = settings
        self.db = db

        # Optional references to downstream services -- attached after
        # construction by the lifespan / DI layer.
        self.ai_processor: AIProcessor | None = None
        self.delivery_service: DeliveryService | None = None
        self.owner_resolver: OwnerResolver | None = None

    # ------------------------------------------------------------------
    # Join meeting
    # ------------------------------------------------------------------

    async def join_meeting(self, meeting: Meeting) -> str:
        """Join a Teams meeting using ACS Call Automation.

        Configures media streaming and transcription WebSocket endpoints,
        creates the call, and persists the connection ID.

        Args:
            meeting: The Meeting ORM object with join_url and schedule data.

        Returns:
            The ACS ``call_connection_id`` for the joined call.

        Raises:
            ACSError: When the call fails to be created.
        """
        async with trace_span(
            "acs.join_meeting",
            attributes={
                "meeting_id": str(meeting.id),
                "subject": meeting.subject,
            },
        ):
            logger.info(
                "Joining meeting %s (%s)",
                meeting.id,
                meeting.subject,
            )

            # Derive WebSocket base from the public BASE_URL.
            ws_base = self.settings.BASE_URL.replace(
                "https://", "wss://"
            ).replace("http://", "ws://")

            media_streaming = MediaStreamingOptions(
                transport_url=f"{ws_base}/ws/audio/{meeting.id}",
                transport_type=StreamingTransportType.WEBSOCKET,
                content_type=MediaStreamingContentType.AUDIO,
                audio_channel_type=MediaStreamingAudioChannelType.UNMIXED,
            )

            transcription = TranscriptionOptions(
                transport_url=f"{ws_base}/ws/transcription/{meeting.id}",
                transport_type=StreamingTransportType.WEBSOCKET,
                locale="en-US",
                start_transcription=True,
            )

            callback_url = f"{self.settings.BASE_URL}/callbacks/acs"

            try:
                call_connection_properties = await asyncio.to_thread(
                    self.client.create_group_call,
                    target_participant=meeting.join_url,
                    callback_url=callback_url,
                    media_streaming=media_streaming,
                    transcription=transcription,
                )

                call_connection_id: str = call_connection_properties.call_connection_id
                logger.info(
                    "ACS call created for meeting %s, call_connection_id=%s",
                    meeting.id,
                    call_connection_id,
                )

                # Update meeting record.
                meeting.status = "in_progress"
                meeting.acs_call_connection_id = call_connection_id
                meeting.actual_start = datetime.now(timezone.utc)
                self.db.add(meeting)
                await self.db.commit()
                await self.db.refresh(meeting)

                metrics["meetings_joined"].add(1)
                return call_connection_id

            except Exception as exc:
                logger.exception("Failed to join meeting %s", meeting.id)
                meeting.status = "failed"
                self.db.add(meeting)
                await self.db.commit()
                metrics["meetings_failed"].add(1)
                raise ACSError(
                    message=f"Failed to join meeting {meeting.id}",
                    call_connection_id=None,
                    operation="join_meeting",
                    cause=exc,
                ) from exc

    # ------------------------------------------------------------------
    # Callback event dispatcher
    # ------------------------------------------------------------------

    async def handle_callback(self, event: dict[str, Any]) -> None:
        """Route an ACS Call Automation CloudEvent to the appropriate handler.

        Args:
            event: CloudEvent dict with ``type`` and ``data`` fields.

        Handles:
            - CallConnected
            - CallDisconnected  (triggers post-processing pipeline)
            - ParticipantsUpdated
            - TranscriptionStarted / TranscriptionStopped
            - MediaStreamingStarted / MediaStreamingStopped
            - PlayCompleted / PlayFailed
        """
        async with trace_span("acs.handle_callback"):
            # Extract event type and call connection ID
            event_type = event.get("type", "")
            event_name = event_type.rsplit(".", 1)[-1] if "." in event_type else event_type
            data = event.get("data", {})
            call_connection_id = data.get("callConnectionId")

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
                await handler(call_connection_id, data)
            else:
                logger.warning("Unhandled ACS event type: %s", event_name)

    # ------------------------------------------------------------------
    # Individual event handlers
    # ------------------------------------------------------------------

    async def _on_call_connected(
        self, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        """Bot successfully joined the meeting."""
        meeting = await self._meeting_by_call_connection(call_connection_id)
        if meeting is None:
            logger.warning(
                "CallConnected for unknown call_connection_id=%s",
                call_connection_id,
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

    async def _on_call_disconnected(
        self, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        """Meeting ended or bot was removed.

        1. Mark meeting as completed, record actual_end.
        2. Fire the post-processing pipeline as a background task.
        """
        meeting = await self._meeting_by_call_connection(call_connection_id)
        if meeting is None:
            logger.warning(
                "CallDisconnected for unknown call_connection_id=%s",
                call_connection_id,
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

        # Trigger post-processing in the background
        asyncio.create_task(self._run_post_processing(meeting.id))

    async def _on_participants_updated(
        self, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        """Someone joined or left -- update the participant roster."""
        meeting = await self._meeting_by_call_connection(call_connection_id)
        if meeting is None:
            return

        participants_data = data.get("participants")
        if participants_data is None:
            return

        now = datetime.now(timezone.utc)

        for p in participants_data:
            raw_id = p.get("rawId", "")
            display_name = p.get("displayName", "Unknown")

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

        # Update participant count on the meeting.
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

    async def _on_transcription_started(
        self, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            "Transcription started for call_connection_id=%s",
            call_connection_id,
        )

    async def _on_transcription_stopped(
        self, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            "Transcription stopped for call_connection_id=%s",
            call_connection_id,
        )

    async def _on_media_streaming_started(
        self, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            "Media streaming started for call_connection_id=%s",
            call_connection_id,
        )

    async def _on_media_streaming_stopped(
        self, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            "Media streaming stopped for call_connection_id=%s",
            call_connection_id,
        )

    async def _on_play_completed(
        self, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            "Play completed for call_connection_id=%s",
            call_connection_id,
        )

    async def _on_play_failed(
        self, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.warning(
            "Play failed for call_connection_id=%s  result=%s",
            call_connection_id,
            data.get("resultInformation"),
        )

    # ------------------------------------------------------------------
    # Explicit transcription control
    # ------------------------------------------------------------------

    async def start_transcription(self, call_connection_id: str) -> None:
        """Explicitly start transcription if not auto-started.

        Args:
            call_connection_id: ACS call connection ID for the active call.
        """
        async with trace_span(
            "acs.start_transcription",
            attributes={"call_connection_id": call_connection_id},
        ):
            logger.info("Starting transcription for call %s", call_connection_id)
            call_connection = self.client.get_call_connection(call_connection_id)
            await asyncio.to_thread(call_connection.start_transcription, locale="en-US")

    async def stop_transcription(self, call_connection_id: str) -> None:
        """Stop transcription before leaving the call.

        Args:
            call_connection_id: ACS call connection ID for the active call.
        """
        async with trace_span(
            "acs.stop_transcription",
            attributes={"call_connection_id": call_connection_id},
        ):
            logger.info("Stopping transcription for call %s", call_connection_id)
            call_connection = self.client.get_call_connection(call_connection_id)
            await asyncio.to_thread(call_connection.stop_transcription)

    # ------------------------------------------------------------------
    # Leave meeting
    # ------------------------------------------------------------------

    async def leave_meeting(self, call_connection_id: str) -> None:
        """Gracefully leave the meeting.

        ``is_for_everyone=False`` ensures only the bot leaves, not all participants.

        Args:
            call_connection_id: ACS call connection ID for the active call.

        Raises:
            ACSError: When the hang-up operation fails.
        """
        async with trace_span(
            "acs.leave_meeting",
            attributes={"call_connection_id": call_connection_id},
        ):
            try:
                logger.info("Leaving call %s", call_connection_id)
                call_connection = self.client.get_call_connection(call_connection_id)
                await asyncio.to_thread(call_connection.hang_up, is_for_everyone=False)
            except Exception as exc:
                raise ACSError(
                    message=f"Failed to leave call {call_connection_id}",
                    call_connection_id=call_connection_id,
                    operation="leave_meeting",
                    cause=exc,
                ) from exc

    # ------------------------------------------------------------------
    # Post-processing pipeline
    # ------------------------------------------------------------------

    async def _run_post_processing(self, meeting_id: uuid.UUID) -> None:
        """Assemble transcript, run AI processing, and deliver the summary.

        Executed as a background task after ``CallDisconnected``.
        """
        async with trace_span(
            "acs.post_processing",
            attributes={"meeting_id": str(meeting_id)},
        ):
            logger.info("Starting post-processing for meeting %s", meeting_id)

            try:
                stmt = (
                    select(Meeting)
                    .where(Meeting.id == meeting_id)
                    .options(
                        selectinload(Meeting.transcript_segments),
                        selectinload(Meeting.participants),
                    )
                )
                result = await self.db.execute(stmt)
                meeting = result.scalar_one_or_none()
                if meeting is None:
                    logger.error(
                        "Post-processing: meeting %s not found", meeting_id
                    )
                    return

                segments = sorted(
                    meeting.transcript_segments, key=lambda s: s.sequence_number
                )

                if not segments:
                    logger.warning(
                        "Post-processing: no transcript segments for meeting %s",
                        meeting_id,
                    )
                    return

                logger.info(
                    "Post-processing meeting %s: %d transcript segments",
                    meeting_id,
                    len(segments),
                )

                # ----- Step 1: AI processing -----
                if self.ai_processor is None:
                    logger.error(
                        "Post-processing: ai_processor not attached to ACSCallService"
                    )
                    return

                ai_result = await self.ai_processor.process_meeting(
                    meeting=meeting,
                    transcript_segments=segments,
                )

                # ----- Step 2: Resolve action-item owners -----
                if self.owner_resolver is not None:
                    action_items = ai_result.get("action_items", [])
                    for item_record in action_items:
                        assigned_name = (
                            item_record.assigned_to_name
                            if hasattr(item_record, "assigned_to_name")
                            else item_record.get("assigned_to_name", "")
                        )
                        if assigned_name:
                            user_id, email = await self.owner_resolver.resolve(
                                assigned_name, meeting.participants
                            )
                            if hasattr(item_record, "assigned_to_user_id"):
                                item_record.assigned_to_user_id = user_id
                                item_record.assigned_to_email = email
                            else:
                                item_record["assigned_to_user_id"] = user_id
                                item_record["assigned_to_email"] = email

                # ----- Step 3: Deliver summary -----
                if self.delivery_service is not None:
                    summary = ai_result.get("summary")
                    action_items_list = ai_result.get("action_items", [])
                    if summary is not None:
                        await self.delivery_service.deliver_summary(
                            meeting=meeting,
                            summary=summary,
                            action_items=action_items_list,
                        )
                        logger.info(
                            "Summary delivered for meeting %s", meeting_id
                        )
                else:
                    logger.warning(
                        "Post-processing: delivery_service not attached; skipping delivery"
                    )

                logger.info("Post-processing completed for meeting %s", meeting_id)

            except Exception:
                logger.exception(
                    "Post-processing failed for meeting %s", meeting_id
                )
                try:
                    stmt = select(Meeting).where(Meeting.id == meeting_id)
                    result = await self.db.execute(stmt)
                    meeting = result.scalar_one_or_none()
                    if meeting is not None:
                        meeting.status = "failed"
                        self.db.add(meeting)
                        await self.db.commit()
                except Exception:
                    logger.exception(
                        "Failed to mark meeting %s as failed", meeting_id
                    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _meeting_by_call_connection(
        self, call_connection_id: str | None
    ) -> Meeting | None:
        """Look up a meeting by its ACS call connection ID."""
        if not call_connection_id:
            return None
        stmt = select(Meeting).where(
            Meeting.acs_call_connection_id == call_connection_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
