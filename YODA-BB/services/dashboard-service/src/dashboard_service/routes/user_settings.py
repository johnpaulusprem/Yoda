"""User settings (preferences) API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard_service.dependencies import get_db
from yoda_foundation.models.subscription import UserPreference
from yoda_foundation.security.auth_dependency import get_current_user
from yoda_foundation.security.context import SecurityContext

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class UserSettingsResponse(BaseModel):
    """Response schema for user settings."""

    user_id: str
    opted_in: bool
    summary_delivery: str  # chat | email | both
    notification_channel: str  # chat | email
    auto_join_enabled: bool
    nudge_enabled: bool
    digest_enabled: bool


class UserSettingsUpdateRequest(BaseModel):
    """Partial-update request schema for user settings."""

    summary_delivery: str | None = None
    notification_channel: str | None = None
    auto_join_enabled: bool | None = None
    nudge_enabled: bool | None = None
    digest_enabled: bool | None = None


# ---------------------------------------------------------------------------
# Default values (returned when no DB record exists)
# ---------------------------------------------------------------------------

_DEFAULTS = UserSettingsResponse(
    user_id="",
    opted_in=True,
    summary_delivery="chat",
    notification_channel="chat",
    auto_join_enabled=True,
    nudge_enabled=True,
    digest_enabled=True,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=UserSettingsResponse)
async def get_user_settings(
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> UserSettingsResponse:
    """Return the current user's preferences.

    If no record exists in the database, sensible defaults are returned.
    """
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == ctx.user_id)
    )
    pref = result.scalar_one_or_none()

    if pref is None:
        return _DEFAULTS.model_copy(update={"user_id": ctx.user_id})

    return UserSettingsResponse(
        user_id=pref.user_id,
        opted_in=pref.opted_in,
        summary_delivery=pref.summary_delivery,
        notification_channel=pref.notification_channel,
        auto_join_enabled=pref.auto_join_enabled,
        nudge_enabled=pref.nudge_enabled,
        digest_enabled=pref.digest_enabled,
    )


@router.patch("", response_model=UserSettingsResponse)
async def update_user_settings(
    body: UserSettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
) -> UserSettingsResponse:
    """Partial update of user preferences (upsert).

    Creates the record if it does not already exist for the authenticated user.
    Only the fields provided in the request body are updated.
    """
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == ctx.user_id)
    )
    pref = result.scalar_one_or_none()

    if pref is None:
        # Create new record with defaults, then overlay provided fields.
        pref = UserPreference(
            user_id=ctx.user_id,
            email=ctx.metadata.get("email", ""),
            display_name=ctx.metadata.get("name", ""),
        )
        db.add(pref)

    update_data = body.model_dump(exclude_none=True)
    for field_name, value in update_data.items():
        setattr(pref, field_name, value)

    await db.commit()
    await db.refresh(pref)

    return UserSettingsResponse(
        user_id=pref.user_id,
        opted_in=pref.opted_in,
        summary_delivery=pref.summary_delivery,
        notification_channel=pref.notification_channel,
        auto_join_enabled=pref.auto_join_enabled,
        nudge_enabled=pref.nudge_enabled,
        digest_enabled=pref.digest_enabled,
    )
