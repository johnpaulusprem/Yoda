"""WebSocket transcription handler for ACS real-time transcription."""
from __future__ import annotations
import json, logging
from datetime import UTC, datetime
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from cxo_ai_companion.models.transcript import TranscriptSegment

logger = logging.getLogger(__name__)
TICKS_PER_SECOND = 10_000_000

def ticks_to_seconds(ticks: int | str) -> float:
    return int(ticks) / TICKS_PER_SECOND

async def handle_transcription_ws(websocket: WebSocket, meeting_id: str, session_factory) -> None:
    await websocket.accept()
    sequence = 0
    logger.info("Transcription WS connected for meeting %s", meeting_id)
    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            result_type = data.get("resultType", data.get("type", ""))
            if result_type != "Final": continue
            text = data.get("text", ""); speaker = data.get("speakerName", data.get("participantRawID", "Unknown"))
            start_ticks = data.get("offset", 0); duration_ticks = data.get("duration", 0)
            start_time = ticks_to_seconds(start_ticks); end_time = start_time + ticks_to_seconds(duration_ticks)
            confidence = data.get("confidence", 0.0)
            if not text.strip(): continue
            sequence += 1
            async with session_factory() as db:
                segment = TranscriptSegment(meeting_id=meeting_id, speaker_name=speaker, text=text, start_time=start_time, end_time=end_time, confidence=confidence, sequence_number=sequence)
                db.add(segment); await db.commit()
            logger.debug("Saved segment #%d for meeting %s", sequence, meeting_id)
    except WebSocketDisconnect:
        logger.info("Transcription WS disconnected for meeting %s (%d segments)", meeting_id, sequence)
    except Exception:
        logger.exception("Transcription WS error for meeting %s", meeting_id)
