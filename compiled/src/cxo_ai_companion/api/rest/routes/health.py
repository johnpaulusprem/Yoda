"""Health check endpoint."""
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from cxo_ai_companion.dependencies import get_db, get_settings

router = APIRouter()

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    checks = {}
    try:
        await db.execute(text("SELECT 1")); checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {e}"
    status = "healthy" if all(v == "healthy" for v in checks.values()) else "degraded"
    return {"status": status, "version": settings.APP_VERSION, "service": settings.APP_NAME, "checks": checks}
