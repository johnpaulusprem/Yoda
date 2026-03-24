"""Health and connectivity check routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from dashboard_service.config import Settings

logger = logging.getLogger(__name__)
router = APIRouter()


class M365StatusResponse(BaseModel):
    """Response schema for the M365 connectivity check."""

    connected: bool
    details: str


@router.get("/health")
async def health():
    """Health check for Azure Container Apps probes."""
    return {"status": "healthy", "service": "dashboard-service"}


@router.get("/api/dashboard/m365-status", response_model=M365StatusResponse)
async def m365_status(request: Request) -> M365StatusResponse:
    """Check whether Azure / M365 credentials are configured.

    Returns ``connected: true`` when ``AZURE_TENANT_ID`` and
    ``AZURE_CLIENT_ID`` are present in the settings.  No auth required --
    this is a lightweight status probe.
    """
    try:
        # Prefer settings from app state (set during lifespan), fall back to fresh instance
        settings: Settings = getattr(request.app.state, "settings", None) or Settings()

        tenant_ok = bool(settings.AZURE_TENANT_ID)
        client_ok = bool(settings.AZURE_CLIENT_ID)

        if tenant_ok and client_ok:
            return M365StatusResponse(
                connected=True,
                details="Azure credentials configured (tenant and client ID present)",
            )

        missing: list[str] = []
        if not tenant_ok:
            missing.append("AZURE_TENANT_ID")
        if not client_ok:
            missing.append("AZURE_CLIENT_ID")

        return M365StatusResponse(
            connected=False,
            details=f"Missing Azure credentials: {', '.join(missing)}",
        )
    except Exception as exc:
        logger.exception("Error checking M365 status")
        return M365StatusResponse(
            connected=False,
            details=f"Error checking M365 status: {exc}",
        )
