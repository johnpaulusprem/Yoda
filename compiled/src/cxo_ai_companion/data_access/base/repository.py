"""Generic async repository pattern for SQLAlchemy models."""
from __future__ import annotations
from typing import Any, Generic, TypeVar
from uuid import UUID
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

class GenericRepository(Generic[T]):
    """Base async repository providing CRUD operations for SQLAlchemy models.

    All write operations use flush() rather than commit(), so transaction
    boundaries are controlled by the caller (typically the route-level session).

    Args:
        session: SQLAlchemy async session for database operations.
        model_class: The ORM model class this repository manages.
    """
    def __init__(self, session: AsyncSession, model_class: type[T]) -> None:
        self._session = session; self._model_class = model_class

    async def get_by_id(self, id: UUID) -> T | None:
        """Fetch a single entity by its UUID primary key.

        Args:
            id: UUID of the entity to retrieve.

        Returns:
            The entity instance, or None if not found.
        """
        result = await self._session.execute(select(self._model_class).where(self._model_class.id == id))
        return result.scalar_one_or_none()

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        """Fetch all entities with pagination.

        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.

        Returns:
            List of entity instances.
        """
        result = await self._session.execute(select(self._model_class).limit(limit).offset(offset))
        return list(result.scalars().all())

    async def create(self, entity: T) -> T:
        """Add a new entity to the session and flush.

        Args:
            entity: The ORM model instance to persist.

        Returns:
            The persisted entity with server-generated fields populated.
        """
        self._session.add(entity); await self._session.flush(); await self._session.refresh(entity); return entity

    async def update(self, entity: T) -> T:
        """Merge and flush changes to an existing entity.

        Args:
            entity: The ORM model instance with updated fields.

        Returns:
            The merged entity instance.
        """
        merged = await self._session.merge(entity); await self._session.flush(); return merged

    async def delete_by_id(self, id: UUID) -> bool:
        """Delete an entity by UUID.

        Args:
            id: UUID of the entity to delete.

        Returns:
            True if deleted, False if not found.
        """
        entity = await self.get_by_id(id)
        if entity is None: return False
        await self._session.delete(entity); await self._session.flush(); return True

    async def count(self, **filters: Any) -> int:
        """Count entities matching optional equality filters.

        Args:
            **filters: Column-name=value pairs for WHERE clauses.

        Returns:
            Integer count of matching records.
        """
        query = select(func.count()).select_from(self._model_class)
        for key, value in filters.items():
            query = query.where(getattr(self._model_class, key) == value)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def exists(self, id: UUID) -> bool:
        """Check whether an entity with the given UUID exists.

        Args:
            id: UUID to check.

        Returns:
            True if the entity exists, False otherwise.
        """
        result = await self._session.execute(select(func.count()).select_from(self._model_class).where(self._model_class.id == id))
        return result.scalar_one() > 0

    async def find_by(self, **filters: Any) -> list[T]:
        """Find all entities matching equality filters.

        Args:
            **filters: Column-name=value pairs for WHERE clauses.

        Returns:
            List of matching entity instances.
        """
        query = select(self._model_class)
        for key, value in filters.items():
            query = query.where(getattr(self._model_class, key) == value)
        result = await self._session.execute(query)
        return list(result.scalars().all())
