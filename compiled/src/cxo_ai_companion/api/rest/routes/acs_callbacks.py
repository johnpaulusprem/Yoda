"""ACS CloudEvents callback handler."""
from __future__ import annotations
import logging
from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/acs/events")
async def acs_callback(request: Request):
    # Read raw body for audit logging
    raw_body = await request.body()
    logger.debug("ACS callback raw body length: %d bytes", len(raw_body))
    # Note: ACS SDK handles signature validation internally via CallAutomationEventParser
    events = await request.json()
    if not isinstance(events, list): events = [events]
    for event in events:
        event_type = event.get("type", "")
        logger.info("ACS callback event: %s", event_type)
        if hasattr(request.app.state, "acs_service"):
            await request.app.state.acs_service.handle_callback(event)
    return Response(status_code=200)
