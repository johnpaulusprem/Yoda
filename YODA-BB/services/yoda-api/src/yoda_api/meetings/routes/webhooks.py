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
import time
from collections import defaultdict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Simple in-memory rate limiter for webhook endpoints
# ---------------------------------------------------------------------------
_webhook_calls: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 100  # max calls per minute per IP
_RATE_WINDOW = 60  # seconds


def _check_rate_limit(client_ip: str) -> bool:
    """Return True if rate limit exceeded."""
    now = time.monotonic()
    calls = _webhook_calls[client_ip]
    # Remove expired entries
    _webhook_calls[client_ip] = [t for t in calls if now - t < _RATE_WINDOW]
    if len(_webhook_calls[client_ip]) >= _RATE_LIMIT:
        return True
    _webhook_calls[client_ip].append(now)
    return False


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
    # 0. Rate limiting
    # ------------------------------------------------------------------
    client_ip = request.client.host if request.client else "unknown"
    if _check_rate_limit(client_ip):
        logger.warning("Rate limit exceeded for webhook from %s", client_ip)
        raise HTTPException(status_code=429, detail="Too many requests")

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

    # ------------------------------------------------------------------
    # 2a. Validate clientState on each notification
    # ------------------------------------------------------------------
    # Graph includes the clientState that was set when the subscription
    # was created.  We must verify it matches to prevent spoofed webhooks.
    expected_client_state = "teams-meeting-assistant"
    validated_notifications = []
    for notification in notifications:
        client_state = notification.get("clientState")
        if client_state != expected_client_state:
            logger.warning(
                "Skipping notification with mismatched clientState",
                extra={
                    "expected": expected_client_state,
                    "received": client_state,
                    "subscriptionId": notification.get("subscriptionId"),
                },
            )
            continue
        validated_notifications.append(notification)

    if not validated_notifications:
        logger.warning("All notifications failed clientState validation")
        return Response(status_code=202)

    # Replace the payload's value with only validated notifications
    validated_payload = {**payload, "value": validated_notifications}

    # Retrieve CalendarWatcher from app state (set during lifespan startup)
    calendar_watcher = request.app.state.calendar_watcher

    # Process asynchronously — Graph requires a response within 3 seconds
    background_tasks.add_task(calendar_watcher.handle_webhook, validated_payload)

    return Response(status_code=202)
