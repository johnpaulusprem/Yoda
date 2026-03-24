"""Notification API routes."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard_service.dependencies import get_db
from yoda_foundation.security.auth_dependency import get_current_user
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.data_access.repositories.notification_repository import NotificationRepository
from yoda_foundation.schemas.notification import NotificationListResponse, NotificationResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    read: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """List notifications for a user, optionally filtered by read status."""
    repo = NotificationRepository(db)
    notifications = await repo.get_by_user(ctx.user_id, read=read, limit=limit)
    unread_count = await repo.get_unread_count(ctx.user_id)
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in notifications],
        total=len(notifications),
        unread_count=unread_count,
    )


@router.get("/count")
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Get the unread notification count for a user."""
    repo = NotificationRepository(db)
    count = await repo.get_unread_count(ctx.user_id)
    return {"unread_count": count}


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Mark a single notification as read."""
    repo = NotificationRepository(db)
    await repo.mark_as_read(notification_id)
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Mark all notifications for a user as read."""
    repo = NotificationRepository(db)
    count = await repo.mark_all_read(ctx.user_id)
    return {"status": "ok", "marked_read": count}
