"""Action item repository."""
from __future__ import annotations
from datetime import UTC, datetime, timedelta
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from cxo_ai_companion.data_access.base.repository import GenericRepository
from cxo_ai_companion.models.action_item import ActionItem

class ActionItemRepository(GenericRepository[ActionItem]):
    """Data access layer for ActionItem entities.

    Extends GenericRepository with meeting-scoped lookups, assignee
    filtering, overdue/due-soon queries, status transitions, and
    nudge-eligible item retrieval for the notification pipeline.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ActionItem)

    async def get_by_meeting(self, meeting_id: UUID) -> list[ActionItem]:
        """Fetch all action items belonging to a specific meeting.

        Args:
            meeting_id: UUID of the meeting.

        Returns:
            List of action items for the meeting.
        """
        result = await self._session.execute(select(ActionItem).where(ActionItem.meeting_id == meeting_id))
        return list(result.scalars().all())

    async def get_by_assignee(self, user_id: str, status: str | None = None) -> list[ActionItem]:
        """Fetch action items assigned to a user, optionally filtered by status.

        Args:
            user_id: The assignee's user ID.
            status: Optional status filter (e.g. "pending", "completed").

        Returns:
            Action items ordered by deadline ascending.
        """
        query = select(ActionItem).where(ActionItem.assigned_to_user_id == user_id)
        if status: query = query.where(ActionItem.status == status)
        result = await self._session.execute(query.order_by(ActionItem.deadline))
        return list(result.scalars().all())

    async def get_overdue(self) -> list[ActionItem]:
        """Fetch action items past their deadline that are still pending or in progress.

        Returns:
            Overdue action items ordered by deadline ascending.
        """
        now = datetime.now(UTC)
        result = await self._session.execute(select(ActionItem).where(ActionItem.deadline < now, ActionItem.status.in_(["pending", "in_progress"])).order_by(ActionItem.deadline))
        return list(result.scalars().all())

    async def get_due_soon(self, hours: int = 48) -> list[ActionItem]:
        """Fetch action items due within the specified time window.

        Args:
            hours: Lookahead window in hours from now.

        Returns:
            Due-soon action items ordered by deadline ascending.
        """
        now = datetime.now(UTC); cutoff = now + timedelta(hours=hours)
        result = await self._session.execute(select(ActionItem).where(ActionItem.deadline >= now, ActionItem.deadline <= cutoff, ActionItem.status.in_(["pending", "in_progress"])).order_by(ActionItem.deadline))
        return list(result.scalars().all())

    async def update_status(self, item_id: UUID, status: str) -> None:
        """Update an action item's status, setting completed_at if completed.

        Args:
            item_id: UUID of the action item.
            status: New status value.
        """
        item = await self.get_by_id(item_id)
        if item:
            item.status = status
            if status == "completed": item.completed_at = datetime.now(UTC)
            await self._session.flush()

    async def get_pending_for_nudge(self, cooldown_hours: int = 4) -> list[ActionItem]:
        """Fetch overdue pending items eligible for a nudge notification.

        Respects a cooldown period to avoid sending nudges too frequently.

        Args:
            cooldown_hours: Minimum hours since last nudge before re-nudging.

        Returns:
            Pending overdue items that haven't been nudged within the cooldown window.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=cooldown_hours)
        result = await self._session.execute(select(ActionItem).where(ActionItem.status == "pending", ActionItem.deadline < datetime.now(UTC)).where((ActionItem.last_nudge_at == None) | (ActionItem.last_nudge_at < cutoff)))
        return list(result.scalars().all())
