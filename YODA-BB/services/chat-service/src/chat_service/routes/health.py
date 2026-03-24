"""Health check endpoint for the chat service.

Provides a lightweight GET /health route used by Azure Container Apps
readiness and liveness probes. Returns service name and status as JSON.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    """Health check for Azure Container Apps probes."""
    return {"status": "healthy", "service": "chat-service"}
