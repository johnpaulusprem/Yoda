"""WebSocket handler for ACS real-time transcription streams -- enterprise edition.

ACS sends transcription data over a WebSocket connection to
``/ws/transcription/{meeting_id}``. This handler parses incoming messages,
stores **Final** transcription segments in the database, and tracks
per-meeting sequencing.

Ported from ``teams-meeting-assistant/app/services/transcription.py`` with:
- CXO exceptions (TranscriptionError)
- Metrics (segments processed, etc.)
- Kept WebSocket handler, tick conversion, Final-only persistence
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cxo_ai_companion.exceptions import TranscriptionError
from cxo_ai_companion.models.meeting import MeetingParticipant
from cxo_ai_companion.models.transcript import TranscriptSegment
from cxo_ai_companion.observability import get_logger, metrics, trace_span

logger = get_logger("services.transcription")

# ACS expresses offsets and durations in 100-nanosecond "ticks".
_TICKS_PER_SECOND = 10_000_000


class TranscriptionHandler:
    """Receives real-time transcription from ACS via WebSocket and persists
    Final results to the database.

    Parses incoming ACS transcription messages, converts tick-based offsets
    to seconds, resolves speaker identities, and stores only Final segments.

    Args:
        db: Async SQLAlchemy session for persisting transcript segments.

    Usage (from the FastAPI WebSocket route)::

        handler = TranscriptionHandler(db=session)
        await handler.handle_connection(websocket, meeting_id)
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # Per-meeting in-memory buffer of segments received during this
        # connection. Keyed by *string* meeting_id.
        self.active_sessions: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Main WebSocket handler
    # ------------------------------------------------------------------

    async def handle_connection(self, websocket: WebSocket, meeting_id: str) -> None:
        """Accept the ACS WebSocket and process messages until the socket closes.

        Runs for the duration of the meeting. Each incoming message is
        expected to be a JSON string conforming to the ACS transcription
        envelope (``kind`` + payload).

        Args:
            websocket: The FastAPI WebSocket connection from ACS.
            meeting_id: String UUID of the meeting being transcribed.
        """
        async with trace_span(
            "transcription.handle_connection",
            attributes={"meeting_id": meeting_id},
        ):
            await websocket.accept()
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

                    kind = data.get("kind", "")

                    if kind == "TranscriptionMetadata":
                        await self._handle_metadata(data, meeting_id)

                    elif kind == "TranscriptionData":
                        sequence_number = await self._handle_transcription_data(
                            data,
                            meeting_id,
                            sequence_number,
                            speaker_map,
                        )

                    else:
                        logger.debug(
                            "Ignoring transcription message kind=%s for meeting %s",
                            kind,
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
        self, data: dict[str, Any], meeting_id: str
    ) -> None:
        """Process a ``TranscriptionMetadata`` message.

        Sent once when ACS first establishes the transcription connection.
        """
        meta = data.get("transcriptionMetadata") or data.get("transcription_metadata")
        if meta is not None:
            logger.info(
                "Transcription metadata for meeting %s: "
                "call_connection_id=%s  correlation_id=%s  locale=%s",
                meeting_id,
                meta.get("callConnectionId"),
                meta.get("correlationId"),
                meta.get("locale"),
            )

    async def _handle_transcription_data(
        self,
        data: dict[str, Any],
        meeting_id: str,
        sequence_number: int,
        speaker_map: dict[str, str],
    ) -> int:
        """Process a ``TranscriptionData`` message.

        Only **Final** results are persisted to avoid duplicate/partial text.
        Intermediate results are logged at DEBUG level and skipped.

        Returns the (possibly incremented) sequence number.
        """
        td = data.get("transcriptionData") or data.get("transcription_data")
        if td is None:
            return sequence_number

        result_status = td.get("resultStatus", td.get("result_status", "Final"))

        if result_status != "Final":
            logger.debug(
                "Skipping %s transcription for meeting %s: %s",
                result_status,
                meeting_id,
                (td.get("text") or "")[:80],
            )
            return sequence_number

        # Resolve the speaker's display name.
        participant_raw_id = td.get("participantRawID") or td.get("participant_raw_id", "")
        speaker_name = speaker_map.get(participant_raw_id, "Unknown Speaker")

        # If we don't know this speaker yet, try to refresh the map.
        if speaker_name == "Unknown Speaker" and participant_raw_id:
            speaker_map.update(await self._build_speaker_map(meeting_id))
            speaker_name = speaker_map.get(participant_raw_id, "Unknown Speaker")

        # Convert ACS ticks to seconds.
        offset = td.get("offset", 0)
        duration = td.get("duration", 0)
        start_time_seconds = offset / _TICKS_PER_SECOND if offset else 0.0
        duration_seconds = duration / _TICKS_PER_SECOND if duration else 0.0
        end_time_seconds = start_time_seconds + duration_seconds

        text = td.get("text", "")
        confidence = td.get("confidence", 0.0)

        # Persist to database.
        try:
            meeting_uuid = uuid.UUID(meeting_id)
        except ValueError:
            raise TranscriptionError(
                message=f"Invalid meeting_id format for transcription: {meeting_id}",
                meeting_id=meeting_id,
            )

        segment = TranscriptSegment(
            meeting_id=meeting_uuid,
            speaker_name=speaker_name,
            speaker_id=participant_raw_id or None,
            text=text,
            start_time=start_time_seconds,
            end_time=end_time_seconds,
            confidence=confidence,
            sequence_number=sequence_number,
        )
        self.db.add(segment)
        await self.db.commit()

        # Track metrics
        metrics["transcript_segments_processed"].add(1)

        # Buffer for in-memory reference
        self.active_sessions.setdefault(meeting_id, []).append(
            {
                "sequence": sequence_number,
                "speaker": speaker_name,
                "text": text,
                "start": start_time_seconds,
                "end": end_time_seconds,
            }
        )

        logger.debug(
            "Stored transcript segment #%d for meeting %s: [%s] %s",
            sequence_number,
            meeting_id,
            speaker_name,
            text[:120] if text else "",
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

        stmt = select(
            func.coalesce(func.max(TranscriptSegment.sequence_number), -1)
        ).where(TranscriptSegment.meeting_id == meeting_uuid)
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
