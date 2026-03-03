"""Action items CRUD routes."""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from cxo_ai_companion.dependencies import get_db
from cxo_ai_companion.data_access.repositories import ActionItemRepository
from cxo_ai_companion.schemas.action_item import ActionItemResponse, ActionItemUpdateRequest, ActionItemListResponse

router = APIRouter()

@router.get("", response_model=ActionItemListResponse)
async def list_action_items(status: str | None = Query(None), assignee: str | None = Query(None), meeting_id: UUID | None = Query(None), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db)):
    """List action items with optional filters by status, assignee, or meeting."""
    repo = ActionItemRepository(db)
    if meeting_id: items = await repo.get_by_meeting(meeting_id)
    elif assignee: items = await repo.get_by_assignee(assignee, status)
    elif status: items = await repo.find_by(status=status)
    else: items = await repo.get_all(limit, offset)
    total = len(items)
    return ActionItemListResponse(items=[ActionItemResponse.model_validate(i) for i in items], total=total)

@router.get("/overdue")
async def get_overdue(db: AsyncSession = Depends(get_db)):
    """Retrieve all overdue action items (past deadline, not completed)."""
    repo = ActionItemRepository(db); items = await repo.get_overdue()
    return {"items": [ActionItemResponse.model_validate(i) for i in items], "total": len(items)}

@router.get("/due-soon")
async def get_due_soon(hours: int = Query(48, ge=1), db: AsyncSession = Depends(get_db)):
    """Retrieve action items due within the specified number of hours."""
    repo = ActionItemRepository(db); items = await repo.get_due_soon(hours)
    return {"items": [ActionItemResponse.model_validate(i) for i in items], "total": len(items)}

@router.get("/{item_id}", response_model=ActionItemResponse)
async def get_action_item(item_id: UUID, db: AsyncSession = Depends(get_db)):
    """Retrieve a single action item by ID."""
    repo = ActionItemRepository(db); item = await repo.get_by_id(item_id)
    if item is None: raise HTTPException(status_code=404, detail="Action item not found")
    return ActionItemResponse.model_validate(item)

@router.patch("/{item_id}", response_model=ActionItemResponse)
async def update_action_item(item_id: UUID, update: ActionItemUpdateRequest, db: AsyncSession = Depends(get_db)):
    """Partially update an action item (status, assignee, deadline, etc.)."""
    repo = ActionItemRepository(db); item = await repo.get_by_id(item_id)
    if item is None: raise HTTPException(status_code=404, detail="Action item not found")
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items(): setattr(item, key, value)
    if "status" in update_data: await repo.update_status(item_id, update_data["status"])
    await db.flush(); await db.refresh(item)
    return ActionItemResponse.model_validate(item)
