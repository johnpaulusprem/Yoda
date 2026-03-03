import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.action_item import ActionItem
from app.schemas.action_item import (
    ActionItemListResponse,
    ActionItemResponse,
    ActionItemUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_STATUSES = {"pending", "in_progress", "completed", "snoozed"}
VALID_PRIORITIES = {"high", "medium", "low"}


@router.get("", response_model=ActionItemListResponse)
async def list_action_items(
    status: str | None = Query(
        default=None,
        description="Filter by status: pending, in_progress, completed, snoozed",
    ),
    user_id: str | None = Query(
        default=None,
        description="Filter by assigned user ID",
    ),
    meeting_id: uuid.UUID | None = Query(
        default=None,
        description="Filter by meeting ID",
    ),
    priority: str | None = Query(
        default=None,
        description="Filter by priority: high, medium, low",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: AsyncSession = Depends(get_db),
) -> ActionItemListResponse:
    """List action items with optional filtering by status, user, meeting, and priority."""
    # Validate filter values
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )
    if priority is not None and priority not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority '{priority}'. Must be one of: {', '.join(sorted(VALID_PRIORITIES))}",
        )

    # Build base query
    stmt = select(ActionItem)
    count_stmt = select(func.count()).select_from(ActionItem)

    # Apply filters
    if status is not None:
        stmt = stmt.where(ActionItem.status == status)
        count_stmt = count_stmt.where(ActionItem.status == status)
    if user_id is not None:
        stmt = stmt.where(ActionItem.assigned_to_user_id == user_id)
        count_stmt = count_stmt.where(ActionItem.assigned_to_user_id == user_id)
    if meeting_id is not None:
        stmt = stmt.where(ActionItem.meeting_id == meeting_id)
        count_stmt = count_stmt.where(ActionItem.meeting_id == meeting_id)
    if priority is not None:
        stmt = stmt.where(ActionItem.priority == priority)
        count_stmt = count_stmt.where(ActionItem.priority == priority)

    # Order by deadline (nulls last), then created_at descending
    stmt = stmt.order_by(
        ActionItem.deadline.asc().nullslast(),
        ActionItem.created_at.desc(),
    )

    # Apply pagination
    stmt = stmt.offset(offset).limit(limit)

    # Execute queries
    result = await db.execute(stmt)
    items = result.scalars().all()

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    logger.info(
        "Listed action items: %d items returned (total: %d, status=%s, "
        "user_id=%s, meeting_id=%s)",
        len(items),
        total,
        status,
        user_id,
        meeting_id,
    )

    return ActionItemListResponse(
        items=[ActionItemResponse.model_validate(item) for item in items],
        total=total,
    )


@router.patch("/{item_id}", response_model=ActionItemResponse)
async def update_action_item(
    item_id: uuid.UUID,
    update: ActionItemUpdate,
    db: AsyncSession = Depends(get_db),
) -> ActionItemResponse:
    """Update an action item's status, priority, deadline, or assignee.

    Called by the UI or by Adaptive Card button actions.
    """
    result = await db.execute(
        select(ActionItem).where(ActionItem.id == item_id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Action item {item_id} not found",
        )

    # Apply only the fields that were provided in the update
    update_data = update.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="No fields to update. Provide at least one field.",
        )

    # Validate status if provided
    if "status" in update_data and update_data["status"] not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{update_data['status']}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    # Validate priority if provided
    if "priority" in update_data and update_data["priority"] not in VALID_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority '{update_data['priority']}'. Must be one of: {', '.join(sorted(VALID_PRIORITIES))}",
        )

    for field, value in update_data.items():
        setattr(item, field, value)

    # If status changed to completed, record completion time
    if update_data.get("status") == "completed" and item.completed_at is None:
        item.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(item)

    logger.info(
        "Updated action item %s: %s",
        item_id,
        update_data,
    )

    return ActionItemResponse.model_validate(item)


@router.post("/{item_id}/complete", response_model=ActionItemResponse)
async def complete_action_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ActionItemResponse:
    """Mark an action item as completed.

    Sets status to 'completed', records completed_at timestamp,
    and clears any active snooze.
    """
    result = await db.execute(
        select(ActionItem).where(ActionItem.id == item_id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Action item {item_id} not found",
        )

    if item.status == "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Action item {item_id} is already completed",
        )

    item.status = "completed"
    item.completed_at = datetime.now(timezone.utc)
    item.snoozed_until = None  # Clear any snooze on completion

    await db.commit()
    await db.refresh(item)

    logger.info("Completed action item %s", item_id)

    return ActionItemResponse.model_validate(item)


@router.post("/{item_id}/snooze", response_model=ActionItemResponse)
async def snooze_action_item(
    item_id: uuid.UUID,
    days: int = Query(
        default=1,
        ge=1,
        le=30,
        description="Number of days to snooze nudges",
    ),
    db: AsyncSession = Depends(get_db),
) -> ActionItemResponse:
    """Snooze nudge reminders for an action item for N days.

    The nudge scheduler will skip this item until snoozed_until has passed.
    Does not change the item's status.
    """
    result = await db.execute(
        select(ActionItem).where(ActionItem.id == item_id)
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Action item {item_id} not found",
        )

    if item.status == "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot snooze a completed action item ({item_id})",
        )

    item.snoozed_until = datetime.now(timezone.utc) + timedelta(days=days)

    await db.commit()
    await db.refresh(item)

    logger.info(
        "Snoozed action item %s for %d day(s) until %s",
        item_id,
        days,
        item.snoozed_until.isoformat(),
    )

    return ActionItemResponse.model_validate(item)
