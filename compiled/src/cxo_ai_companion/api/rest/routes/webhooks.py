"""Graph webhook handler.

Graph API requires webhook responses within 3 seconds. Heavy processing
(DB queries, Graph API calls) is offloaded to BackgroundTasks so we
return 202 immediately.
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, BackgroundTasks, Request, Response
from starlette.responses import PlainTextResponse

from cxo_ai_companion.dependencies import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


async def _process_notification(app_state: object, notification: dict) -> None:
    """Process a single Graph notification in the background."""
    try:
        if hasattr(app_state, "calendar_watcher"):
            await app_state.calendar_watcher.handle_webhook(notification)
    except Exception:
        logger.exception("Error processing Graph notification in background")


@router.post("/graph")
async def graph_webhook(request: Request, background_tasks: BackgroundTasks):
    # Handle validation token for subscription creation
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        return PlainTextResponse(content=validation_token, media_type="text/plain")
    settings = get_settings()
    body = await request.json()
    notifications = body.get("value", [])
    for notification in notifications:
        # Validate clientState matches our secret
        client_state = notification.get("clientState", "")
        if settings.GRAPH_WEBHOOK_SECRET and client_state != settings.GRAPH_WEBHOOK_SECRET:
            logger.warning("Webhook clientState mismatch, skipping notification")
            continue
        resource = notification.get("resource", "")
        change_type = notification.get("changeType", "")
        logger.info("Graph webhook: %s on %s", change_type, resource)
        # Dispatch to background to avoid Graph 3-second timeout
        background_tasks.add_task(_process_notification, request.app.state, notification)
    return Response(status_code=202)
