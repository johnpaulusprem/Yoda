from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    """Health check for Azure Container Apps probes."""
    return {"status": "healthy", "service": "teams-meeting-assistant"}
