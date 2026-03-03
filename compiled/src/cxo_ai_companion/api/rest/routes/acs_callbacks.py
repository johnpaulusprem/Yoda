"""ACS CloudEvents callback handler."""
from __future__ import annotations
import logging
from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/acs/events")
async def acs_callback(request: Request):
    events = await request.json()
    if not isinstance(events, list): events = [events]
    for event in events:
        event_type = event.get("type", "")
        logger.info("ACS callback event: %s", event_type)
        if hasattr(request.app.state, "acs_service"):
            await request.app.state.acs_service.handle_callback(event)
    return Response(status_code=200)
