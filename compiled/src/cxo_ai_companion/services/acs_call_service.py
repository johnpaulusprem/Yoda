"""ACS Call Automation service -- enterprise edition.

Joins Teams meetings, handles callback events, and orchestrates the
post-meeting processing pipeline.

Ported from ``teams-meeting-assistant/app/services/acs_call_service.py`` with:
- CXO exceptions (ACSError)
- Tracing spans via observability
- Metrics tracking (meetings_joined, meetings_failed)
- Session-factory pattern: each operation creates its own DB session
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from azure.communication.callautomation import CallAutomationClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
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

    Uses a session-factory pattern: each operation (join, callback, post-processing)
    creates its own short-lived DB session, avoiding stale-session issues from
    long-lived service instances stored in ``app.state``.

    Args:
        settings: Application settings (ACS_CONNECTION_STRING, BASE_URL).
        session_factory: Async session factory for creating per-operation DB sessions.
    """

    def __init__(self, settings: Any, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.client = CallAutomationClient.from_connection_string(
            settings.ACS_CONNECTION_STRING
        )
        self.settings = settings
        self._session_factory = session_factory

        # Optional references to downstream services -- attached after
        # construction by the lifespan / DI layer.
        self.ai_processor: AIProcessor | None = None
        self.delivery_service: DeliveryService | None = None
        self.owner_resolver: OwnerResolver | None = None

    # ------------------------------------------------------------------
    # Join meeting
    # ------------------------------------------------------------------

    async def join_meeting(self, meeting_id: uuid.UUID) -> str:
        """Join a Teams meeting using ACS Call Automation.

        Uses the ACS REST API ``createCall`` with ``teamsMeetingLink`` to join
        an existing Teams meeting.  The Python SDK v1.5.0 ``CreateCallRequest``
        model does not expose ``teamsMeetingLink``, so we pass raw JSON bytes
        to the generated client which accepts ``IO[bytes]``.

        Args:
            meeting_id: UUID of the Meeting record to join.

        Returns:
            The ACS ``call_connection_id`` for the joined call, or empty
            string if the meeting was skipped (wrong status).

        Raises:
            ACSError: When the call fails to be created.
        """
        async with trace_span(
            "acs.join_meeting",
            attributes={"meeting_id": str(meeting_id)},
        ):
            async with self._session_factory() as db:
                stmt = select(Meeting).where(Meeting.id == meeting_id)
                result = await db.execute(stmt)
                meeting = result.scalar_one_or_none()

                if meeting is None:
                    raise ACSError(
                        message=f"Meeting {meeting_id} not found",
                        call_connection_id=None,
                        operation="join_meeting",
                    )

                if meeting.status not in ("scheduled", "failed"):
                    logger.info(
                        "Skipping join for meeting %s — status is '%s'",
                        meeting_id,
                        meeting.status,
                    )
                    return ""

                logger.info(
                    "Joining meeting %s (%s)",
                    meeting.id,
                    meeting.subject,
                )

                if not meeting.join_url:
                    raise ACSError(
                        message=f"Meeting {meeting_id} has no join_url",
                        call_connection_id=None,
                        operation="join_meeting",
                    )

                # Derive WebSocket base from the public BASE_URL.
                ws_base = self.settings.BASE_URL.replace(
                    "https://", "wss://"
                ).replace("http://", "ws://")

                callback_url = f"{self.settings.BASE_URL}/api/callbacks/acs/events"

                # Build the raw JSON request body with teamsMeetingLink.
                #
                # Why we can't use the SDK's public methods:
                #   - create_call / create_group_call expect CommunicationIdentifier
                #     targets — they don't support teamsMeetingLink
                # Why we can't use _client.create_call(IO[bytes]):
                #   - HMAC signing policy calls body.encode("utf-8"), needs str.
                #     BytesIO/bytes don't have .encode() → AttributeError.
                # Why we can't pass a dict through create_call_request=:
                #   - _serialize.body strips unknown fields (teamsMeetingLink lost).
                #
                # Solution: build HttpRequest ourselves with json=dict (body is
                # str), run through SDK pipeline.  See _create_call_with_teams_link.
                request_body = {
                    "teamsMeetingLink": meeting.join_url,
                    "callbackUri": callback_url,
                    "sourceDisplayName": "CXO AI Companion",
                    "mediaStreamingOptions": {
                        "transportUrl": f"{ws_base}/ws/audio/{meeting.id}",
                        "transportType": "websocket",
                        "contentType": "audio",
                        "audioChannelType": "unmixed",
                    },
                    "transcriptionOptions": {
                        "transportUrl": f"{ws_base}/ws/transcription/{meeting.id}",
                        "transportType": "websocket",
                        "locale": "en-US",
                        "startTranscription": True,
                    },
                }

                try:
                    call_connection_properties = await asyncio.to_thread(
                        self._create_call_with_teams_link,
                        request_body,
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
                    db.add(meeting)
                    await db.commit()

                    metrics["meetings_joined"].add(1)
                    return call_connection_id

                except Exception as exc:
                    logger.exception("Failed to join meeting %s", meeting.id)
                    meeting.status = "failed"
                    db.add(meeting)
                    await db.commit()
                    metrics["meetings_failed"].add(1)
                    raise ACSError(
                        message=f"Failed to join meeting {meeting_id}",
                        call_connection_id=None,
                        operation="join_meeting",
                        cause=exc,
                    ) from exc

    # ------------------------------------------------------------------
    # Callback event dispatcher
    # ------------------------------------------------------------------

    async def handle_callback(self, event: dict[str, Any]) -> None:
        """Route an ACS Call Automation CloudEvent to the appropriate handler.

        Creates a fresh DB session per callback to avoid stale-session issues.

        Args:
            event: CloudEvent dict with ``type`` and ``data`` fields.
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
                async with self._session_factory() as db:
                    await handler(db, call_connection_id, data)
            else:
                logger.warning("Unhandled ACS event type: %s", event_name)

    # ------------------------------------------------------------------
    # Individual event handlers
    # ------------------------------------------------------------------

    async def _on_call_connected(
        self, db: AsyncSession, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        """Bot successfully joined the meeting."""
        meeting = await self._meeting_by_call_connection(db, call_connection_id)
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
            db.add(meeting)
            await db.commit()

    async def _on_call_disconnected(
        self, db: AsyncSession, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        """Meeting ended or bot was removed.

        1. Mark meeting as completed, record actual_end.
        2. Fire the post-processing pipeline as a background task.
        """
        meeting = await self._meeting_by_call_connection(db, call_connection_id)
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
        db.add(meeting)
        await db.commit()

        # Trigger post-processing in the background (creates its own session)
        asyncio.create_task(self._run_post_processing(meeting.id))

    async def _on_participants_updated(
        self, db: AsyncSession, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        """Someone joined or left -- update the participant roster."""
        meeting = await self._meeting_by_call_connection(db, call_connection_id)
        if meeting is None:
            return

        participants_data = data.get("participants")
        if participants_data is None:
            return

        now = datetime.now(timezone.utc)

        for p in participants_data:
            identifier = p.get("identifier", {})
            raw_id = identifier.get("rawId", "") if isinstance(identifier, dict) else p.get("rawId", "")
            display_name = p.get("displayName", "Unknown")

            stmt = select(MeetingParticipant).where(
                MeetingParticipant.meeting_id == meeting.id,
                MeetingParticipant.user_id == raw_id,
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing is None:
                participant = MeetingParticipant(
                    meeting_id=meeting.id,
                    user_id=raw_id,
                    display_name=display_name,
                    role="attendee",
                    joined_at=now,
                )
                db.add(participant)
            else:
                if existing.display_name == "Unknown" and display_name != "Unknown":
                    existing.display_name = display_name
                    db.add(existing)

        # Update participant count on the meeting.
        count_stmt = select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting.id
        )
        count_result = await db.execute(count_stmt)
        meeting.participant_count = len(count_result.scalars().all())
        db.add(meeting)
        await db.commit()

        logger.info(
            "Participants updated for meeting %s, count=%d",
            meeting.id,
            meeting.participant_count,
        )

    async def _on_transcription_started(
        self, db: AsyncSession, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            "Transcription started for call_connection_id=%s",
            call_connection_id,
        )

    async def _on_transcription_stopped(
        self, db: AsyncSession, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            "Transcription stopped for call_connection_id=%s",
            call_connection_id,
        )

    async def _on_media_streaming_started(
        self, db: AsyncSession, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            "Media streaming started for call_connection_id=%s",
            call_connection_id,
        )

    async def _on_media_streaming_stopped(
        self, db: AsyncSession, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            "Media streaming stopped for call_connection_id=%s",
            call_connection_id,
        )

    async def _on_play_completed(
        self, db: AsyncSession, call_connection_id: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            "Play completed for call_connection_id=%s",
            call_connection_id,
        )

    async def _on_play_failed(
        self, db: AsyncSession, call_connection_id: str | None, data: dict[str, Any]
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
        """Explicitly start transcription if not auto-started."""
        async with trace_span(
            "acs.start_transcription",
            attributes={"call_connection_id": call_connection_id},
        ):
            logger.info("Starting transcription for call %s", call_connection_id)
            call_connection = self.client.get_call_connection(call_connection_id)
            await asyncio.to_thread(call_connection.start_transcription, locale="en-US")

    async def stop_transcription(self, call_connection_id: str) -> None:
        """Stop transcription before leaving the call."""
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
    # Post-processing pipeline (with single retry)
    # ------------------------------------------------------------------

    async def _run_post_processing(self, meeting_id: uuid.UUID) -> None:
        """Assemble transcript, run AI processing, and deliver the summary.

        Executed as a background task after ``CallDisconnected``.
        Retries once after 30 seconds if the first attempt fails.
        """
        for attempt in range(2):
            try:
                await self._run_post_processing_attempt(meeting_id)
                return
            except Exception:
                if attempt == 0:
                    logger.warning(
                        "Post-processing attempt 1 failed for meeting %s, retrying in 30s",
                        meeting_id,
                    )
                    await asyncio.sleep(30)
                else:
                    logger.exception(
                        "Post-processing failed after retry for meeting %s",
                        meeting_id,
                    )
                    try:
                        async with self._session_factory() as db:
                            stmt = select(Meeting).where(Meeting.id == meeting_id)
                            result = await db.execute(stmt)
                            meeting = result.scalar_one_or_none()
                            if meeting is not None:
                                meeting.status = "failed"
                                db.add(meeting)
                                await db.commit()
                    except Exception:
                        logger.exception(
                            "Failed to mark meeting %s as failed", meeting_id
                        )

    async def _run_post_processing_attempt(self, meeting_id: uuid.UUID) -> None:
        """Single attempt at post-processing."""
        async with trace_span(
            "acs.post_processing",
            attributes={"meeting_id": str(meeting_id)},
        ):
            logger.info("Starting post-processing for meeting %s", meeting_id)

            async with self._session_factory() as db:
                stmt = (
                    select(Meeting)
                    .where(Meeting.id == meeting_id)
                    .options(
                        selectinload(Meeting.transcript_segments),
                        selectinload(Meeting.participants),
                    )
                )
                result = await db.execute(stmt)
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_call_with_teams_link(self, request_body: dict) -> object:
        """Send a createCall request with teamsMeetingLink via the SDK pipeline.

        Constructs the HttpRequest manually with ``json=request_body`` so the
        body is stored as a ``str`` (required by the HMAC signing policy),
        then runs it through the SDK's HTTP pipeline and deserializes the
        response as ``CallConnectionProperties``.
        """
        from azure.communication.callautomation._generated.operations._operations import (
            build_azure_communication_call_automation_service_create_call_request,
        )
        from azure.core.exceptions import HttpResponseError

        generated = self.client._client

        _request = build_azure_communication_call_automation_service_create_call_request(
            content_type="application/json",
            api_version=generated._config.api_version,
            json=request_body,
            content=None,
            headers={},
            params={},
        )

        path_format_arguments = {
            "endpoint": generated._serialize.url(
                "self._config.endpoint",
                generated._config.endpoint,
                "str",
                skip_quote=True,
            ),
        }
        _request.url = generated._client.format_url(
            _request.url, **path_format_arguments
        )

        pipeline_response = generated._client._pipeline.run(_request, stream=False)
        response = pipeline_response.http_response

        if response.status_code not in [201]:
            from azure.communication.callautomation._generated import models as _models
            error = generated._deserialize.failsafe_deserialize(
                _models.CommunicationErrorResponse, pipeline_response
            )
            raise HttpResponseError(response=response, model=error)

        return generated._deserialize(
            "CallConnectionProperties", pipeline_response.http_response
        )

    async def _meeting_by_call_connection(
        self, db: AsyncSession, call_connection_id: str | None
    ) -> Meeting | None:
        """Look up a meeting by its ACS call connection ID."""
        if not call_connection_id:
            return None
        stmt = select(Meeting).where(
            Meeting.acs_call_connection_id == call_connection_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
