"""Action item CRUD endpoints for the meeting service.

Exposes list, update, complete, and snooze operations on action items.
Results are scoped to the authenticated user via Azure AD JWT -- users
see only items assigned to them, items from meetings they organized, or
items assigned to their direct reports (resolved via Graph API with a
one-hour in-memory cache). Supports filtering by status, priority,
meeting, and owner relationship.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_api.dependencies import get_db
from yoda_foundation.models.action_item import ActionItem
from yoda_foundation.models.meeting import Meeting
from yoda_foundation.schemas.action_item import (
    ActionItemListResponse,
    ActionItemResponse,
    ActionItemUpdate,
)
from yoda_api.meetings.utils.azure_ad_auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_STATUSES = {"pending", "in_progress", "completed", "snoozed"}
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_OWNER_FILTERS = {"assigned_to_me", "assigned_by_me", "my_reports"}

# Cache for direct reports lookups (user_id -> (expiry_timestamp, report_ids))
_direct_reports_cache: dict[str, tuple[float, list[str]]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


async def _get_direct_reports(user_id: str, graph_client: object | None) -> list[str]:
    """Get direct report user IDs from Graph API, cached for 1 hour.

    Args:
        user_id: Azure AD user ID of the manager.
        graph_client: GraphClient instance (from app.state).

    Returns:
        List of Azure AD user IDs for the manager's direct reports.
        Returns an empty list if the Graph client is unavailable or the
        API call fails.
    """
    import time

    now = time.monotonic()
    cached = _direct_reports_cache.get(user_id)
    if cached is not None:
        expiry, report_ids = cached
        if now < expiry:
            return report_ids

    if graph_client is None:
        return []

    try:
        reports = await graph_client.get_direct_reports(user_id)
        report_ids = [r.get("id", "") for r in reports if r.get("id")]
        _direct_reports_cache[user_id] = (now + _CACHE_TTL_SECONDS, report_ids)
        return report_ids
    except Exception:
        logger.warning("Failed to get direct reports for %s", user_id)
        return []


@router.get("", response_model=ActionItemListResponse)
async def list_action_items(
    request: Request,
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
    filter: str | None = Query(
        default=None,
        description="Owner filter: assigned_to_me, assigned_by_me, or my_reports",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> ActionItemListResponse:
    """List action items with optional filtering by status, user, meeting, and priority.

    Results are scoped to action items assigned to the authenticated user
    or belonging to meetings the user organized.
    """
    auth_user_id = _user.get("sub", "")

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
    if filter is not None and filter not in VALID_OWNER_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filter '{filter}'. Must be one of: {', '.join(sorted(VALID_OWNER_FILTERS))}",
        )

    # Build base query
    stmt = select(ActionItem)
    count_stmt = select(func.count()).select_from(ActionItem)

    # Apply owner filter if specified; otherwise fall back to default scope
    if filter == "assigned_to_me":
        owner_scope = ActionItem.assigned_to_user_id == auth_user_id
        stmt = stmt.where(owner_scope)
        count_stmt = count_stmt.where(owner_scope)
    elif filter == "assigned_by_me":
        # Items from meetings where the authenticated user is the organizer
        organizer_scope = ActionItem.meeting_id.in_(
            select(Meeting.id).where(Meeting.organizer_id == auth_user_id)
        )
        stmt = stmt.where(organizer_scope)
        count_stmt = count_stmt.where(organizer_scope)
    elif filter == "my_reports":
        # Resolve direct reports via Graph API (cached for 1 hour)
        graph_client = getattr(request.app.state, "graph_client", None)
        report_ids = await _get_direct_reports(auth_user_id, graph_client)
        if report_ids:
            reports_scope = ActionItem.assigned_to_user_id.in_(report_ids)
            stmt = stmt.where(reports_scope)
            count_stmt = count_stmt.where(reports_scope)
        else:
            # No direct reports found -- fall back to default user scope
            # so the endpoint still returns something useful
            user_scope = or_(
                ActionItem.assigned_to_user_id == auth_user_id,
                ActionItem.meeting_id.in_(
                    select(Meeting.id).where(Meeting.organizer_id == auth_user_id)
                ),
            )
            stmt = stmt.where(user_scope)
            count_stmt = count_stmt.where(user_scope)
    else:
        # Default: scope to action items the user is assigned to or from
        # meetings they organized
        user_scope = or_(
            ActionItem.assigned_to_user_id == auth_user_id,
            ActionItem.meeting_id.in_(
                select(Meeting.id).where(Meeting.organizer_id == auth_user_id)
            ),
        )
        stmt = stmt.where(user_scope)
        count_stmt = count_stmt.where(user_scope)

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
        "user_id=%s, meeting_id=%s, filter=%s)",
        len(items),
        total,
        status,
        user_id,
        meeting_id,
        filter,
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
    _user: dict = Depends(get_current_user),
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
    _user: dict = Depends(get_current_user),
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
    _user: dict = Depends(get_current_user),
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
