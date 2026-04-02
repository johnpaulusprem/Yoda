"""Admin API routes for user management."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from yoda_api.dependencies import get_db
from yoda_foundation.models.subscription import UserPreference
from yoda_api.meetings.schemas.admin import (
    CreateUserRequest,
    UpdateUserRequest,
    UserListResponse,
    UserResponse,
)
from yoda_api.meetings.utils.azure_ad_auth import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_response(user: UserPreference) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        user_id=user.user_id,
        display_name=user.display_name,
        email=user.email,
        opted_in=user.opted_in,
        summary_delivery=user.summary_delivery,
        nudge_enabled=user.nudge_enabled,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
    )


@router.get("", response_model=UserListResponse)
async def list_users(
    opted_in: bool | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
) -> UserListResponse:
    query = select(UserPreference)
    count_q = select(func.count()).select_from(UserPreference)
    if opted_in is not None:
        query = query.where(UserPreference.opted_in == opted_in)
        count_q = count_q.where(UserPreference.opted_in == opted_in)
    total = (await db.execute(count_q)).scalar_one()
    result = await db.execute(
        query.order_by(UserPreference.created_at.desc()).limit(limit).offset(offset)
    )
    users = result.scalars().all()
    return UserListResponse(items=[_to_response(u) for u in users], total=total)


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
) -> UserResponse:
    user = UserPreference(
        user_id=body.user_id,
        display_name=body.display_name,
        email=body.email,
        opted_in=True,
        summary_delivery=body.summary_delivery,
        nudge_enabled=body.nudge_enabled,
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")
    logger.info("Admin created user", extra={"user_id": body.user_id})
    return _to_response(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
) -> UserResponse:
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    logger.info("Admin updated user", extra={"user_id": user_id, "updates": list(updates.keys())})
    return _to_response(user)


@router.delete("/{user_id}", status_code=204, response_model=None)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_admin),
) -> None:
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
    logger.info("Admin deleted user", extra={"user_id": user_id})
