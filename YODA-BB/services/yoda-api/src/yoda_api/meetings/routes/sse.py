"""SSE endpoint for real-time meeting updates.

Streams live transcript chunks, participant changes, and lifecycle events
to connected clients during an active meeting.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory event queues per meeting. Each meeting_id maps to a list of
# asyncio.Queue instances — one per connected SSE client.
_meeting_events: dict[str, list[asyncio.Queue]] = {}


def publish_meeting_event(meeting_id: str, event: dict) -> None:
    """Push an event to all SSE clients subscribed to a meeting.

    Called from bot_events.py when transcript chunks or lifecycle events arrive.
    Non-blocking: uses put_nowait so the caller is never delayed by slow clients.
    """
    queues = _meeting_events.get(meeting_id)
    if not queues:
        return
    for queue in queues:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "SSE queue full for meeting %s — dropping event",
                meeting_id,
            )


@router.get("/api/meetings/{meeting_id}/events")
async def meeting_events(meeting_id: str, request: Request) -> StreamingResponse:
    """SSE endpoint for live meeting updates.

    Clients connect with EventSource and receive JSON-encoded events as they
    happen. A keepalive comment is sent every 30 seconds to prevent proxies
    from closing idle connections.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)

    if meeting_id not in _meeting_events:
        _meeting_events[meeting_id] = []
    _meeting_events[meeting_id].append(queue)

    logger.info(
        "SSE client connected for meeting %s (total clients: %d)",
        meeting_id,
        len(_meeting_events[meeting_id]),
    )

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # SSE comment as heartbeat — keeps the connection alive
                    yield ": keepalive\n\n"
        finally:
            _meeting_events[meeting_id].remove(queue)
            if not _meeting_events[meeting_id]:
                del _meeting_events[meeting_id]
            logger.info(
                "SSE client disconnected for meeting %s",
                meeting_id,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering for SSE
        },
    )
