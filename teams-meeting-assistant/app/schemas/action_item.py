"""Pydantic schemas for action items."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ActionItemResponse(BaseModel):
    """Full response schema for an action item. Mirrors the ActionItem model."""

    id: uuid.UUID
    meeting_id: uuid.UUID
    description: str
    assigned_to_name: str
    assigned_to_user_id: str | None = None
    assigned_to_email: str | None = None
    deadline: datetime | None = None
    priority: str = "medium"
    status: str = "pending"
    nudge_count: int = 0
    last_nudged_at: datetime | None = None
    completed_at: datetime | None = None
    snoozed_until: datetime | None = None
    source_quote: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActionItemUpdate(BaseModel):
    """Partial update schema for an action item. All fields are optional.

    Used by PATCH /action-items/{item_id} and by Adaptive Card submit actions.
    Only the fields that are provided will be applied to the model.
    """

    status: str | None = Field(
        default=None,
        description="New status: pending, in_progress, completed, snoozed",
    )
    priority: str | None = Field(
        default=None,
        description="New priority: high, medium, low",
    )
    deadline: datetime | None = Field(
        default=None,
        description="Updated deadline (ISO 8601 datetime with timezone)",
    )
    assigned_to_name: str | None = Field(
        default=None,
        description="Updated assignee display name",
    )
    assigned_to_user_id: str | None = Field(
        default=None,
        description="Updated assignee Azure AD user ID",
    )
    assigned_to_email: str | None = Field(
        default=None,
        description="Updated assignee email address",
    )


class ActionItemListResponse(BaseModel):
    """Paginated list of action items with total count for the UI."""

    items: list[ActionItemResponse]
    total: int = Field(
        description="Total number of action items matching the filter criteria"
    )
