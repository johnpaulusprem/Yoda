"""Dependency injection primitives for the meeting service.

Creates the async SQLAlchemy engine and session factory at module level from
``Settings.DATABASE_URL``. Provides a ``get_db`` FastAPI dependency that
yields a per-request async session. The session factory is also consumed by
lifespan-scoped services (NudgeScheduler, PostProcessingService) that manage
their own session lifecycles.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from meeting_service.config import Settings

settings = Settings()

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async DB session."""
    async with async_session_factory() as session:
        yield session
