"""Weekly digest API routes."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_worker.dependencies import async_session_factory, get_db
from yoda_worker.schemas import DigestGenerateRequest, WeeklyDigestResponse
from yoda_worker.services.weekly_digest_service import WeeklyDigestService

from yoda_foundation.models.insight import WeeklyDigest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/digests/latest", response_model=WeeklyDigestResponse)
async def get_latest_digest(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the most recent weekly digest for the specified user."""
    result = await db.execute(
        select(WeeklyDigest)
        .where(WeeklyDigest.user_id == user_id)
        .order_by(WeeklyDigest.created_at.desc())
        .limit(1)
    )
    digest = result.scalar_one_or_none()
    if digest is None:
        raise HTTPException(status_code=404, detail="No digest found for this user")

    return WeeklyDigestResponse.model_validate(digest)


@router.post("/api/digests/generate", response_model=WeeklyDigestResponse)
async def generate_digest(
    request: Request,
    body: DigestGenerateRequest,
):
    """Trigger generation of a weekly digest for the specified user."""
    ai_connector = getattr(request.app.state, "ai_connector", None)
    delivery_service = getattr(request.app.state, "delivery_service", None)

    service = WeeklyDigestService(
        ai_connector=ai_connector,
        delivery_service=delivery_service,
        db_session_factory=async_session_factory,
    )

    digest = await service.generate_digest(user_id=body.user_id)
    return WeeklyDigestResponse.model_validate(digest)
