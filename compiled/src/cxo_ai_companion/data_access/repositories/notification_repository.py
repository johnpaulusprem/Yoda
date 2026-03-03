"""Repository for notification persistence operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from cxo_ai_companion.data_access.base.repository import GenericRepository
from cxo_ai_companion.models.notification import Notification


class NotificationRepository(GenericRepository[Notification]):
    """Data access layer for Notification entities.

    Extends GenericRepository with user-scoped queries, unread counts,
    and bulk/single read-marking operations.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Notification)

    async def get_by_user(
        self, user_id: str, read: bool | None = None, limit: int = 50
    ) -> list[Notification]:
        """Fetch notifications for a user, optionally filtered by read status."""
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        if read is not None:
            stmt = stmt.where(Notification.read == read)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_unread_count(self, user_id: str) -> int:
        """Return the count of unread notifications for a user."""
        result = await self._session.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read == False)  # noqa: E712
        )
        return result.scalar_one()

    async def mark_as_read(self, notification_id: UUID) -> None:
        """Mark a single notification as read."""
        await self._session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(read=True)
        )
        await self._session.flush()

    async def mark_all_read(self, user_id: str) -> int:
        """Mark all notifications for a user as read. Returns count updated."""
        result = await self._session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read == False)  # noqa: E712
            .values(read=True)
        )
        await self._session.flush()
        return result.rowcount
