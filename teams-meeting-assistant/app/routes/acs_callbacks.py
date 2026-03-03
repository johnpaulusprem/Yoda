"""ACS Call Automation callback route.

Spec reference: Section 7.2

ACS posts CloudEvents to ``POST /callbacks/acs`` whenever call state
changes (connected, disconnected, participants updated, transcription
started/stopped, etc.).  This route parses the events and delegates
each one to :class:`app.services.acs_call_service.ACSCallService`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.acs import ACSCallEvent

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_acs_service(request: Request):
    """Retrieve the ACSCallService instance from app state.

    The service is initialised during the lifespan startup and stored on
    ``app.state.acs_service``.
    """
    return request.app.state.acs_service


@router.post("/acs")
async def acs_callback(
    request: Request,
    acs_service=Depends(_get_acs_service),
) -> Response:
    """Receive ACS Call Automation event callbacks.

    ACS sends an **array** of CloudEvents in the request body.  Each
    event is parsed and routed through
    :meth:`ACSCallService.handle_callback`.

    Returns ``200 OK`` to acknowledge receipt.
    """
    body: Any = await request.json()

    # ACS can send a single event or an array of events.
    events: list[dict]
    if isinstance(body, list):
        events = body
    elif isinstance(body, dict):
        events = [body]
    else:
        logger.warning("Unexpected ACS callback body type: %s", type(body))
        return Response(status_code=400)

    for raw_event in events:
        try:
            # Validate through Pydantic so downstream code gets typed access.
            parsed = ACSCallEvent.model_validate(raw_event)
            logger.info(
                "Received ACS event: type=%s  call_connection_id=%s",
                parsed.type,
                parsed.call_connection_id,
            )
            await acs_service.handle_callback(parsed)
        except Exception:
            # Log and continue -- don't let a single bad event prevent the
            # rest of the batch from being processed.
            logger.exception(
                "Error handling ACS callback event: %s",
                raw_event.get("type", "<unknown>") if isinstance(raw_event, dict) else raw_event,
            )

    return Response(status_code=200)
