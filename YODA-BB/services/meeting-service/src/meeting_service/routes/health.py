"""Health check endpoint for the meeting service.

Returns service name, status, and version for infrastructure monitoring
and container orchestration readiness probes.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    """Health check for Azure Container Apps probes."""
    return {"status": "healthy", "service": "teams-meeting-assistant"}
