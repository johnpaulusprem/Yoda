"""Pydantic v2 schemas for notifications."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    """API response schema for a single user notification.

    Serialized from the Notification ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique notification identifier (UUID).
        user_id: Azure AD object ID of the recipient.
        type: Notification category (e.g. summary_ready, action_due, nudge).
        title: Short headline for the notification.
        message: Full notification message body.
        read: Whether the user has read this notification.
        related_entity_type: Type of the related entity (meeting, action_item, etc.).
        related_entity_id: UUID of the related entity, for deep linking.
        created_at: Timestamp when the notification was created.
    """

    id: uuid.UUID
    user_id: str
    type: str
    title: str
    message: str
    read: bool
    related_entity_type: str | None = None
    related_entity_id: uuid.UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """Paginated response wrapper for listing notifications.

    Includes an unread count for badge display in the UI.

    Attributes:
        items: List of notification objects for the current page.
        total: Total number of notifications matching the query.
        unread_count: Number of unread notifications across all pages.
    """

    items: list[NotificationResponse]
    total: int
    unread_count: int
