"""Webhook routes for Microsoft Graph change notifications.

Graph sends two types of requests to this endpoint:

1. **Validation** -- When a subscription is first created, Graph sends a
   POST with a ``validationToken`` query parameter.  The server must
   respond with HTTP 200 and echo the token as plain text.

2. **Notifications** -- When subscribed resources change, Graph sends a
   POST with a JSON body containing one or more change notifications.
   The server must respond with HTTP 202 within 3 seconds and process
   the notifications asynchronously.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/graph")
async def graph_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """Receive Microsoft Graph change notifications.

    This endpoint is registered as the ``notificationUrl`` when creating
    Graph subscriptions.  It handles both the initial validation handshake
    and subsequent change notification payloads.

    **Validation flow** (subscription creation):
        Graph sends ``?validationToken=<token>`` as a query parameter.
        We respond with ``200 OK`` and the token echoed back as plain text.

    **Notification flow** (resource changes):
        Graph POSTs a JSON body with a ``value`` array of notifications.
        We immediately return ``202 Accepted`` and hand processing off to
        a ``BackgroundTask`` so we stay within Graph's 3-second timeout.
    """
    # ------------------------------------------------------------------
    # 1. Handle Graph validation handshake
    # ------------------------------------------------------------------
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        logger.info("Graph webhook validation request received")
        return PlainTextResponse(
            content=validation_token,
            status_code=200,
        )

    # ------------------------------------------------------------------
    # 2. Handle change notifications
    # ------------------------------------------------------------------
    try:
        payload: dict = await request.json()
    except Exception:
        logger.exception("Failed to parse webhook JSON body")
        return Response(status_code=400)

    notifications = payload.get("value", [])
    logger.info(
        "Received Graph change notifications",
        extra={"count": len(notifications)},
    )

    # Retrieve CalendarWatcher from app state (set during lifespan startup)
    calendar_watcher = request.app.state.calendar_watcher

    # Process asynchronously — Graph requires a response within 3 seconds
    background_tasks.add_task(calendar_watcher.handle_webhook, payload)

    return Response(status_code=202)
