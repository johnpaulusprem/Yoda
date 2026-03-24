"""Repository for project persistence operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yoda_foundation.data_access.base.repository import GenericRepository
from yoda_foundation.models.project import Project


class ProjectRepository(GenericRepository[Project]):
    """Data access layer for Project entities.

    Extends GenericRepository with owner-scoped lookups, active project
    filtering, and eager-loaded meeting associations.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Project)

    async def get_with_meetings(self, project_id: UUID) -> Project | None:
        """Fetch a project with its linked meetings eagerly loaded."""
        result = await self._session.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.meetings))
        )
        return result.scalar_one_or_none()

    async def get_by_owner(self, user_id: str) -> list[Project]:
        """Fetch all projects owned by a user."""
        result = await self._session.execute(
            select(Project)
            .where(Project.owner_user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active(self) -> list[Project]:
        """Fetch all active projects."""
        result = await self._session.execute(
            select(Project)
            .where(Project.status == "active")
            .order_by(Project.created_at.desc())
        )
        return list(result.scalars().all())
