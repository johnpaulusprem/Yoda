from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GraphSubscription(Base, TimestampMixin):
    __tablename__ = "graph_subscriptions"

    subscription_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    resource: Mapped[str] = mapped_column(String, nullable=False)
    expiration: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )  # active, expired, failed


class UserPreference(Base, TimestampMixin):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    opted_in: Mapped[bool] = mapped_column(Boolean, default=True)
    summary_delivery: Mapped[str] = mapped_column(
        String, default="chat"
    )  # chat, email, both
    nudge_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
