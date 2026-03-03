"""Notification API routes."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cxo_ai_companion.dependencies import get_db
from cxo_ai_companion.data_access.repositories.notification_repository import NotificationRepository
from cxo_ai_companion.schemas.notification import NotificationListResponse, NotificationResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    user_id: str = Query(...),
    read: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List notifications for a user, optionally filtered by read status."""
    repo = NotificationRepository(db)
    notifications = await repo.get_by_user(user_id, read=read, limit=limit)
    unread_count = await repo.get_unread_count(user_id)
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in notifications],
        total=len(notifications),
        unread_count=unread_count,
    )


@router.get("/count")
async def get_unread_count(
    user_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get the unread notification count for a user."""
    repo = NotificationRepository(db)
    count = await repo.get_unread_count(user_id)
    return {"unread_count": count}


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Mark a single notification as read."""
    repo = NotificationRepository(db)
    await repo.mark_as_read(notification_id)
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_notifications_read(
    user_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Mark all notifications for a user as read."""
    repo = NotificationRepository(db)
    count = await repo.mark_all_read(user_id)
    return {"status": "ok", "marked_read": count}
