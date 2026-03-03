"""Graph webhook handler."""
from __future__ import annotations
import logging
from fastapi import APIRouter, Request, Response
from starlette.responses import PlainTextResponse

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/graph")
async def graph_webhook(request: Request):
    # Handle validation token for subscription creation
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        return PlainTextResponse(content=validation_token, media_type="text/plain")
    body = await request.json()
    notifications = body.get("value", [])
    for notification in notifications:
        resource = notification.get("resource", "")
        change_type = notification.get("changeType", "")
        logger.info("Graph webhook: %s on %s", change_type, resource)
        # Dispatch to calendar_watcher service
        if hasattr(request.app.state, "calendar_watcher"):
            await request.app.state.calendar_watcher.handle_notification(notification)
    return Response(status_code=202)
