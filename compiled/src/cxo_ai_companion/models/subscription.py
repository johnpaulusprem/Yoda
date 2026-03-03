"""GraphSubscription and UserPreference ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from cxo_ai_companion.models.base import Base, TimestampMixin, UUIDMixin


class GraphSubscription(Base, UUIDMixin, TimestampMixin):
    """Tracks active Microsoft Graph webhook subscriptions for calendar monitoring."""

    __tablename__ = "graph_subscriptions"

    subscription_id: Mapped[str] = mapped_column(
        String, nullable=False, unique=True
    )
    resource: Mapped[str] = mapped_column(String, nullable=False)
    change_type: Mapped[str] = mapped_column(
        String, nullable=False, default="created,updated,deleted"
    )
    notification_url: Mapped[str] = mapped_column(String, nullable=False)
    expiration: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )  # active | expired | failed


class UserPreference(Base, UUIDMixin, TimestampMixin):
    """Per-user settings controlling notification delivery, auto-join, and digests."""

    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    notification_channel: Mapped[str] = mapped_column(
        String, nullable=False, default="chat"
    )  # chat | email | both
    auto_join_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    nudge_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
