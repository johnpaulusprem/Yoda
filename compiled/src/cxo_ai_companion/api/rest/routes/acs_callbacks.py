"""ACS CloudEvents callback handler.

Per ACS documentation, callback events include an Authorization header
with a JWT signed by ``https://acscallautomation.communication.azure.com``.
We validate this JWT when ACS_ENDPOINT is configured; otherwise we warn
and proceed (graceful degradation for development).
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, Request, Response

from cxo_ai_companion.dependencies import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# ACS callback JWT signing keys endpoint
_ACS_JWKS_URI = "https://acscallautomation.communication.azure.com/calling/keys"
_ACS_ISSUER = "https://acscallautomation.communication.azure.com"

# Singleton JWKS client — caches signing keys automatically
_jwks_client = None


def _get_jwks_client():
    """Return the cached PyJWKClient singleton."""
    global _jwks_client
    if _jwks_client is None:
        import jwt as pyjwt
        _jwks_client = pyjwt.PyJWKClient(_ACS_JWKS_URI)
    return _jwks_client


async def _validate_acs_jwt(request: Request) -> bool:
    """Validate the ACS callback JWT from the Authorization header.

    Returns True if validation passes or is skipped (no ACS_ENDPOINT configured).
    Returns False if validation fails (invalid or missing JWT when ACS_ENDPOINT is set).
    """
    settings = get_settings()
    if not settings.ACS_ENDPOINT:
        # No ACS endpoint configured — can't validate audience, skip
        return True

    auth_header = request.headers.get("authorization")
    if not auth_header:
        logger.warning("ACS callback: no Authorization header (expected JWT from ACS)")
        # In production, ACS always sends this header — reject if missing
        if not settings.DEBUG:
            return False
        return True

    try:
        import jwt as pyjwt

        token = auth_header.split()[1]  # "Bearer <token>"
        jwks_client = _get_jwks_client()
        pyjwt.decode(
            token,
            jwks_client.get_signing_key_from_jwt(token).key,
            algorithms=["RS256"],
            issuer=_ACS_ISSUER,
            audience=settings.ACS_ENDPOINT,
        )
        return True
    except Exception:
        logger.warning("ACS callback: JWT validation failed", exc_info=True)
        return False


@router.post("/acs/events")
async def acs_callback(request: Request):
    # Validate ACS JWT (warn on failure, don't block in dev)
    jwt_valid = await _validate_acs_jwt(request)
    if not jwt_valid:
        settings = get_settings()
        if not settings.DEBUG:
            logger.error("ACS callback: rejecting request with invalid JWT in production")
            return Response(status_code=401)

    events = await request.json()
    if not isinstance(events, list):
        events = [events]
    for event in events:
        event_type = event.get("type", "")
        logger.info("ACS callback event: %s", event_type)
        if hasattr(request.app.state, "acs_service"):
            await request.app.state.acs_service.handle_callback(event)
    return Response(status_code=200)
