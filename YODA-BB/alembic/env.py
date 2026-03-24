"""Alembic environment configuration for async PostgreSQL migrations."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Import all models so they register with Base.metadata ─────────
from yoda_foundation.models.base import Base
from yoda_foundation.models.meeting import Meeting, MeetingParticipant  # noqa: F401
from yoda_foundation.models.transcript import TranscriptSegment  # noqa: F401
from yoda_foundation.models.summary import MeetingSummary  # noqa: F401
from yoda_foundation.models.action_item import ActionItem  # noqa: F401
from yoda_foundation.models.subscription import GraphSubscription, UserPreference  # noqa: F401
from yoda_foundation.models.document import Document, DocumentChunk  # noqa: F401
from yoda_foundation.models.insight import MeetingInsight, WeeklyDigest  # noqa: F401
from yoda_foundation.models.chat import ChatSession, ChatMessage  # noqa: F401
from yoda_foundation.models.notification import Notification  # noqa: F401
from yoda_foundation.models.project import Project  # noqa: F401

# Alembic Config object (provides access to alembic.ini values)
config = context.config

# Interpret the alembic.ini [loggers] section for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData object for autogenerate support
target_metadata = Base.metadata

# ── Resolve DATABASE_URL from environment ─────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is required. "
        "Example: postgresql+asyncpg://yoda:yoda_dev@localhost:5432/yoda"
    )

# Ensure we use the asyncpg driver
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Execute migrations against the given connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with an async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = DATABASE_URL

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations -- delegates to async runner."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
