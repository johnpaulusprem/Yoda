"""WebSocket handler for ACS real-time transcription streams.

Spec reference: Section 6.5

ACS sends transcription data over a WebSocket connection to
``/ws/transcription/{meeting_id}``.  This handler parses incoming
messages, stores **Final** transcription segments in the database,
and tracks per-meeting sequencing.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.schemas.acs import ACSTranscriptionMessage

logger = logging.getLogger(__name__)

# ACS expresses offsets and durations in 100-nanosecond "ticks".
_TICKS_PER_SECOND = 10_000_000


class TranscriptionHandler:
    """Receives real-time transcription from ACS via WebSocket and persists
    Final results to the database.

    Usage (from the FastAPI WebSocket route)::

        handler = TranscriptionHandler(db=session)
        await handler.handle_connection(websocket, meeting_id)
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # Per-meeting in-memory buffer of segments received during this
        # connection.  Keyed by *string* meeting_id so we can look it up
        # quickly from the WebSocket URL parameter.
        self.active_sessions: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Main WebSocket handler
    # ------------------------------------------------------------------

    async def handle_connection(self, websocket: WebSocket, meeting_id: str) -> None:
        """Accept the ACS WebSocket and process messages until the socket closes.

        Runs for the duration of the meeting.  Each incoming message is
        expected to be a JSON string conforming to the ACS transcription
        envelope (``kind`` + payload).
        """
        logger.info(
            "Transcription WebSocket connected for meeting %s", meeting_id
        )

        # Initialize the per-meeting buffer.
        self.active_sessions[meeting_id] = []

        # Determine the starting sequence number by checking how many
        # segments already exist in the DB (e.g. from a reconnection).
        sequence_number = await self._get_next_sequence_number(meeting_id)

        # Build a mapping of participantRawID -> display_name from the
        # participant roster so we can label speakers.
        speaker_map = await self._build_speaker_map(meeting_id)

        try:
            while True:
                raw = await websocket.receive_text()

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(
                        "Non-JSON message on transcription WS for meeting %s",
                        meeting_id,
                    )
                    continue

                # Parse through the Pydantic model for validation, but fall
                # back gracefully if the payload is unexpected.
                try:
                    message = ACSTranscriptionMessage.model_validate(data)
                except Exception:
                    logger.warning(
                        "Could not validate transcription message for meeting %s: %s",
                        meeting_id,
                        data.get("kind", "<unknown>"),
                    )
                    continue

                if message.kind == "TranscriptionMetadata":
                    await self._handle_metadata(message, meeting_id)

                elif message.kind == "TranscriptionData":
                    sequence_number = await self._handle_transcription_data(
                        message,
                        meeting_id,
                        sequence_number,
                        speaker_map,
                    )

                # "WordData" and other kinds are logged but not persisted.
                else:
                    logger.debug(
                        "Ignoring transcription message kind=%s for meeting %s",
                        message.kind,
                        meeting_id,
                    )

        except WebSocketDisconnect:
            logger.info(
                "Transcription WebSocket disconnected for meeting %s",
                meeting_id,
            )
        except Exception:
            logger.exception(
                "Transcription WebSocket error for meeting %s", meeting_id
            )
        finally:
            # Clean up the in-memory buffer.
            segments_received = len(self.active_sessions.pop(meeting_id, []))
            logger.info(
                "Transcription session ended for meeting %s, %d segments received",
                meeting_id,
                segments_received,
            )

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_metadata(
        self, message: ACSTranscriptionMessage, meeting_id: str
    ) -> None:
        """Process a ``TranscriptionMetadata`` message.

        This is sent once when ACS first establishes the transcription
        connection.  We log the metadata for diagnostics.
        """
        meta = message.transcription_metadata
        if meta is not None:
            logger.info(
                "Transcription metadata for meeting %s: "
                "call_connection_id=%s  correlation_id=%s  locale=%s",
                meeting_id,
                meta.call_connection_id,
                meta.correlation_id,
                meta.locale,
            )

    async def _handle_transcription_data(
        self,
        message: ACSTranscriptionMessage,
        meeting_id: str,
        sequence_number: int,
        speaker_map: dict[str, str],
    ) -> int:
        """Process a ``TranscriptionData`` message.

        Only **Final** results are persisted to avoid duplicate/partial text.
        Intermediate results are logged at DEBUG level and skipped.

        Returns the (possibly incremented) sequence number.
        """
        td = message.transcription_data
        if td is None:
            return sequence_number

        result_status = td.result_status  # "Final" or "Intermediate"

        if result_status != "Final":
            logger.debug(
                "Skipping %s transcription for meeting %s: %s",
                result_status,
                meeting_id,
                td.text[:80] if td.text else "",
            )
            return sequence_number

        # Resolve the speaker's display name.
        participant_raw_id = td.participant_raw_id or ""
        speaker_name = speaker_map.get(participant_raw_id, "Unknown Speaker")

        # If we don't know this speaker yet, try to refresh the map.
        if speaker_name == "Unknown Speaker" and participant_raw_id:
            speaker_map = await self._build_speaker_map(meeting_id)
            speaker_name = speaker_map.get(participant_raw_id, "Unknown Speaker")

        # Convert ACS ticks to seconds.
        start_time_seconds = td.offset / _TICKS_PER_SECOND if td.offset else 0.0
        duration_seconds = td.duration / _TICKS_PER_SECOND if td.duration else 0.0
        end_time_seconds = start_time_seconds + duration_seconds

        # Persist to database.
        try:
            meeting_uuid = uuid.UUID(meeting_id)
        except ValueError:
            logger.error(
                "Invalid meeting_id format for transcription: %s", meeting_id
            )
            return sequence_number

        segment = TranscriptSegment(
            meeting_id=meeting_uuid,
            speaker_name=speaker_name,
            speaker_id=participant_raw_id or None,
            text=td.text,
            start_time=start_time_seconds,
            end_time=end_time_seconds,
            confidence=td.confidence,
            sequence_number=sequence_number,
        )
        self.db.add(segment)
        await self.db.commit()

        # Buffer for in-memory reference (useful for debugging or
        # mid-meeting features).
        self.active_sessions.setdefault(meeting_id, []).append(
            {
                "sequence": sequence_number,
                "speaker": speaker_name,
                "text": td.text,
                "start": start_time_seconds,
                "end": end_time_seconds,
            }
        )

        logger.debug(
            "Stored transcript segment #%d for meeting %s: [%s] %s",
            sequence_number,
            meeting_id,
            speaker_name,
            td.text[:120] if td.text else "",
        )

        return sequence_number + 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_next_sequence_number(self, meeting_id: str) -> int:
        """Return the next sequence_number to assign for a given meeting.

        Checks the database for the current maximum so that reconnections
        pick up where they left off.
        """
        try:
            meeting_uuid = uuid.UUID(meeting_id)
        except ValueError:
            return 0

        stmt = select(func.coalesce(func.max(TranscriptSegment.sequence_number), -1)).where(
            TranscriptSegment.meeting_id == meeting_uuid
        )
        result = await self.db.execute(stmt)
        current_max: int = result.scalar_one()
        return current_max + 1

    async def _build_speaker_map(self, meeting_id: str) -> dict[str, str]:
        """Build a mapping from ACS participant raw ID to display name.

        Queries the ``meeting_participants`` table for all known
        participants of this meeting.
        """
        try:
            meeting_uuid = uuid.UUID(meeting_id)
        except ValueError:
            return {}

        stmt = select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_uuid
        )
        result = await self.db.execute(stmt)
        participants = result.scalars().all()

        mapping: dict[str, str] = {}
        for p in participants:
            if p.user_id:
                mapping[p.user_id] = p.display_name
        return mapping
