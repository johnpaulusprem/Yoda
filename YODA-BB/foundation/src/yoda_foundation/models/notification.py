"""Notification ORM model for user alerts and activity updates."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from yoda_foundation.models.base import Base, TimestampMixin, UUIDMixin


class Notification(Base, UUIDMixin, TimestampMixin):
    """A notification delivered to a user about system events.

    Sent via Teams chat or Adaptive Card when key events occur, such as
    a summary being ready, an action item assigned, or a conflict detected.

    Attributes:
        user_id: Azure AD object ID of the notification recipient.
        type: Event category (summary_ready | action_assigned | action_overdue |
            document_shared | meeting_reminder | conflict_detected).
        title: Short headline for the notification.
        message: Full notification body text.
        read: Whether the user has acknowledged / dismissed the notification.
        related_entity_type: Kind of entity this links to (meeting | action_item | document).
        related_entity_id: UUID of the related entity for deep-linking.
    """

    __tablename__ = "notifications"

    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # summary_ready | action_assigned | action_overdue | document_shared | meeting_reminder | conflict_detected
    title: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    related_entity_type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # meeting | action_item | document
    related_entity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
