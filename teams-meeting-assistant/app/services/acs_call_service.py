"""ACS Call Automation service -- joins Teams meetings, handles callback events,
and orchestrates the post-meeting processing pipeline.

Spec reference: Section 6.4
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from azure.communication.callautomation import CallAutomationClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.schemas.acs import ACSCallEvent, ACSCallParticipant

if TYPE_CHECKING:
    from app.services.ai_processor import AIProcessor
    from app.services.delivery import DeliveryService
    from app.services.owner_resolver import OwnerResolver

logger = logging.getLogger(__name__)


class ACSCallService:
    """Manages ACS Call Automation lifecycle: join, monitor, leave, and
    trigger post-meeting processing when the call ends."""

    def __init__(self, settings: Settings, db: AsyncSession) -> None:
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

        The Python SDK v1.5.0 public methods (``create_call``, ``create_group_call``,
        ``connect_call``) do NOT support ``teamsMeetingLink``.  The only way to join
        a Teams meeting is to call the generated client's ``create_call`` directly
        with raw JSON bytes (``IO[bytes]``) containing the ``teamsMeetingLink`` field.

        The SDK's ``TranscriptionOptions`` / ``MediaStreamingOptions`` models are also
        incomplete — ``transportUrl``, ``transportType``, ``startTranscription`` are
        silently dropped.  So we include them in the raw JSON payload as well.

        Returns the ``call_connection_id``.
        """
        logger.info(
            "Joining meeting %s (%s)",
            meeting.id,
            meeting.subject,
        )

        if not meeting.join_url:
            raise ValueError(f"Meeting {meeting.id} has no join_url")

        # Derive WebSocket base from the public BASE_URL.
        ws_base = self.settings.BASE_URL.replace("https://", "wss://").replace(
            "http://", "ws://"
        )

        callback_url = f"{self.settings.BASE_URL}/callbacks/acs"

        # Build raw JSON request with teamsMeetingLink.
        #
        # Why we can't use the SDK's public methods:
        #   - create_call / create_group_call expect CommunicationIdentifier
        #     targets — they don't support teamsMeetingLink
        #   - connect_call only supports server_call_id / group_call_id / room_id
        #
        # Why we can't use _client.create_call(IO[bytes]):
        #   - The HMAC signing policy (_shared/policy.py:101) calls
        #     body.encode("utf-8"), which requires body to be str.
        #     BytesIO and bytes both fail with AttributeError.
        #
        # Why we can't pass a dict through create_call_request=:
        #   - _serialize.body(dict, "CreateCallRequest") strips unknown
        #     fields — teamsMeetingLink gets dropped.
        #
        # Solution: build the HttpRequest ourselves with json=dict (which
        # stores body as a str) and run it through the SDK's pipeline.
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

            # The meeting object may come from a different AsyncSession
            # (for example, the route session), so merge it into the service
            # session before persisting state changes.
            meeting.status = "in_progress"
            meeting.acs_call_connection_id = call_connection_id
            meeting.actual_start = datetime.now(timezone.utc)
            persisted_meeting = await self.db.merge(meeting)
            await self.db.commit()
            await self.db.refresh(persisted_meeting)

            return call_connection_id

        except Exception:
            logger.exception("Failed to join meeting %s", meeting.id)
            meeting.status = "failed"
            persisted_meeting = await self.db.merge(meeting)
            await self.db.commit()
            await self.db.refresh(persisted_meeting)
            raise

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

    # ------------------------------------------------------------------
    # Callback event dispatcher
    # ------------------------------------------------------------------

    async def handle_callback(self, event: dict | ACSCallEvent) -> None:
        """Route an ACS Call Automation CloudEvent to the appropriate handler.

        Handles:
            - CallConnected
            - CallDisconnected  (triggers post-processing pipeline)
            - ParticipantsUpdated
            - TranscriptionStarted / TranscriptionStopped
            - MediaStreamingStarted / MediaStreamingStopped
            - PlayCompleted / PlayFailed
        """
        # Accept either a raw dict (from the route) or a pre-parsed model.
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

        # Ensure the meeting is marked in_progress (it should already be from
        # join_meeting, but this confirms the call actually connected).
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

        # Trigger post-processing in the background so we don't block the
        # callback response.  asyncio.create_task keeps it alive in the
        # running event loop.
        asyncio.create_task(self._run_post_processing(meeting.id))

    async def _on_participants_updated(self, event: ACSCallEvent) -> None:
        """Someone joined or left -- update the participant roster."""
        meeting = await self._meeting_by_call_connection(event.call_connection_id)
        if meeting is None:
            return

        if event.data.participants is None:
            return

        now = datetime.now(timezone.utc)

        for p in event.data.participants:
            raw_id = p.raw_id or ""
            display_name = p.display_name or "Unknown"

            # Try to find an existing participant record.
            stmt = select(MeetingParticipant).where(
                MeetingParticipant.meeting_id == meeting.id,
                MeetingParticipant.user_id == raw_id,
            )
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing is None:
                # New participant joining.
                participant = MeetingParticipant(
                    meeting_id=meeting.id,
                    user_id=raw_id,
                    display_name=display_name,
                    role="attendee",
                    joined_at=now,
                )
                self.db.add(participant)
            else:
                # Update display name if it was previously unknown.
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

    async def _on_transcription_started(self, event: ACSCallEvent) -> None:
        """ACS transcription stream is now active."""
        logger.info(
            "Transcription started for call_connection_id=%s",
            event.call_connection_id,
        )

    async def _on_transcription_stopped(self, event: ACSCallEvent) -> None:
        """ACS transcription stream has ended."""
        logger.info(
            "Transcription stopped for call_connection_id=%s",
            event.call_connection_id,
        )

    async def _on_media_streaming_started(self, event: ACSCallEvent) -> None:
        """ACS media (audio) streaming is now active."""
        logger.info(
            "Media streaming started for call_connection_id=%s",
            event.call_connection_id,
        )

    async def _on_media_streaming_stopped(self, event: ACSCallEvent) -> None:
        """ACS media (audio) streaming has ended."""
        logger.info(
            "Media streaming stopped for call_connection_id=%s",
            event.call_connection_id,
        )

    async def _on_play_completed(self, event: ACSCallEvent) -> None:
        """An audio announcement finished playing."""
        logger.info(
            "Play completed for call_connection_id=%s",
            event.call_connection_id,
        )

    async def _on_play_failed(self, event: ACSCallEvent) -> None:
        """An audio announcement failed to play."""
        logger.warning(
            "Play failed for call_connection_id=%s  result=%s",
            event.call_connection_id,
            event.data.result_information,
        )

    # ------------------------------------------------------------------
    # Explicit transcription control
    # ------------------------------------------------------------------

    async def start_transcription(self, call_connection_id: str) -> None:
        """Explicitly start transcription if not auto-started."""
        logger.info("Starting transcription for call %s", call_connection_id)
        call_connection = self.client.get_call_connection(call_connection_id)
        await asyncio.to_thread(call_connection.start_transcription, locale="en-US")

    async def stop_transcription(self, call_connection_id: str) -> None:
        """Stop transcription before leaving."""
        logger.info("Stopping transcription for call %s", call_connection_id)
        call_connection = self.client.get_call_connection(call_connection_id)
        await asyncio.to_thread(call_connection.stop_transcription)

    # ------------------------------------------------------------------
    # Leave meeting
    # ------------------------------------------------------------------

    async def leave_meeting(self, call_connection_id: str) -> None:
        """Gracefully leave the meeting.

        Called when a meeting runs too long, on error, or during app shutdown.
        ``is_for_everyone=False`` ensures only the bot leaves, not all participants.
        """
        logger.info("Leaving call %s", call_connection_id)
        call_connection = self.client.get_call_connection(call_connection_id)
        await asyncio.to_thread(call_connection.hang_up, is_for_everyone=False)

    # ------------------------------------------------------------------
    # Post-processing pipeline
    # ------------------------------------------------------------------

    async def _run_post_processing(self, meeting_id: uuid.UUID) -> None:
        """Assemble transcript, run AI processing, and deliver the summary.

        This is executed as a background task after ``CallDisconnected``.
        """
        logger.info("Starting post-processing for meeting %s", meeting_id)

        try:
            # Re-query the meeting with relationships loaded so we get a
            # consistent snapshot.
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
            # Mark the meeting as failed so the UI can show it and allow
            # manual re-processing.
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
