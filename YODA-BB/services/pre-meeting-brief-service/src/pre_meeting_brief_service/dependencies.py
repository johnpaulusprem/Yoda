"""Dependency injection -- DB sessions, Graph client, AI connector, cache."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pre_meeting_brief_service.config import Settings

logger = logging.getLogger(__name__)

settings = Settings()

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async DB session."""
    async with async_session_factory() as session:
        yield session
