"""Notification service for creating and managing user notifications."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cxo_ai_companion.data_access.repositories.notification_repository import NotificationRepository
from cxo_ai_companion.models.notification import Notification

logger = logging.getLogger(__name__)


class NotificationService:
    """Manages user notifications: creation, retrieval, and read-state tracking.

    Provides CRUD operations for in-app notifications linked to meetings,
    action items, or other entities.

    Args:
        db_session_factory: Async session factory for notification persistence.
    """

    def __init__(self, db_session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = db_session_factory

    async def create(
        self,
        user_id: str,
        type: str,
        title: str,
        message: str,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
    ) -> Notification:
        """Create and persist a new notification.

        Args:
            user_id: Azure AD user ID of the notification recipient.
            type: Notification type (e.g., ``nudge``, ``summary``, ``escalation``).
            title: Short notification title.
            message: Full notification message body.
            entity_type: Optional related entity type (e.g., ``meeting``, ``action_item``).
            entity_id: Optional UUID of the related entity.

        Returns:
            The persisted Notification instance.
        """
        async with self._session_factory() as db:
            repo = NotificationRepository(db)
            notification = Notification(
                user_id=user_id,
                type=type,
                title=title,
                message=message,
                related_entity_type=entity_type,
                related_entity_id=entity_id,
            )
            created = await repo.create(notification)
            await db.commit()
            logger.info("Notification created: type=%s user=%s", type, user_id)
            return created

    async def get_for_user(
        self, user_id: str, read: bool | None = None, limit: int = 50
    ) -> list[Notification]:
        """Retrieve notifications for a user with optional read-state filter.

        Args:
            user_id: Azure AD user ID.
            read: Filter by read state (True/False), or None for all.
            limit: Maximum number of notifications to return.

        Returns:
            List of Notification instances.
        """
        async with self._session_factory() as db:
            repo = NotificationRepository(db)
            return await repo.get_by_user(user_id, read=read, limit=limit)

    async def get_unread_count(self, user_id: str) -> int:
        """Get the count of unread notifications for a user.

        Args:
            user_id: Azure AD user ID.

        Returns:
            Number of unread notifications.
        """
        async with self._session_factory() as db:
            repo = NotificationRepository(db)
            return await repo.get_unread_count(user_id)

    async def mark_read(self, notification_id: UUID) -> None:
        """Mark a single notification as read.

        Args:
            notification_id: UUID of the notification to mark as read.
        """
        async with self._session_factory() as db:
            repo = NotificationRepository(db)
            await repo.mark_as_read(notification_id)
            await db.commit()

    async def mark_all_read(self, user_id: str) -> int:
        """Mark all notifications for a user as read.

        Args:
            user_id: Azure AD user ID.

        Returns:
            Number of notifications marked as read.
        """
        async with self._session_factory() as db:
            repo = NotificationRepository(db)
            count = await repo.mark_all_read(user_id)
            await db.commit()
            return count
