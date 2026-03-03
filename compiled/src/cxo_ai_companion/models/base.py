"""SQLAlchemy 2.0 async base with UUID primary keys and timestamp tracking."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models.

    All application models inherit from this class to share a single
    metadata registry and benefit from SQLAlchemy 2.0 declarative mapping.
    """

    pass


class TimestampMixin:
    """Mixin that adds automatic timestamp tracking to any model.

    Both columns use server-side ``now()`` defaults so timestamps are
    consistent regardless of application-server clock skew.

    Attributes:
        created_at: Row creation timestamp (UTC, set once by the DB).
        updated_at: Last-modification timestamp (UTC, refreshed on every UPDATE).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDMixin:
    """Mixin that provides a UUID v4 primary key column.

    Generates a new UUID automatically on insert via Python's ``uuid4()``.

    Attributes:
        id: Auto-generated UUID v4 primary key.
    """

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
