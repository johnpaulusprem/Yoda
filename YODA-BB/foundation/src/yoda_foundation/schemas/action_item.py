"""Pydantic v2 schemas for action items."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ActionItemResponse(BaseModel):
    """API response schema for an action item extracted from a meeting.

    Serialized from the ActionItem ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique action item identifier (UUID).
        meeting_id: Foreign key to the parent meeting.
        description: What needs to be done.
        assigned_to_name: Display name of the assignee.
        assigned_to_user_id: Azure AD object ID of the assignee.
        assigned_to_email: Email of the assignee.
        deadline: Due date/time for the action item.
        priority: Priority level (high, medium, low).
        status: Current status (pending, in_progress, completed, cancelled).
        source_quote: Original transcript excerpt that produced this item.
        nudge_count: Number of reminder nudges sent.
        last_nudged_at: Timestamp of the most recent nudge.
        completed_at: Timestamp when the item was marked completed.
        snoozed_until: If snoozed, the datetime until which nudges are paused.
        confidence: AI confidence score for extraction accuracy (0.0--1.0).
        created_at: Record creation timestamp.
        updated_at: Record last-update timestamp.
    """

    id: uuid.UUID
    meeting_id: uuid.UUID
    description: str
    assigned_to_name: str
    assigned_to_user_id: str | None = None
    assigned_to_email: str | None = None
    deadline: datetime | None = None
    priority: str = "medium"
    status: str = "pending"
    source_quote: str | None = None
    nudge_count: int = 0
    last_nudged_at: datetime | None = None
    completed_at: datetime | None = None
    snoozed_until: datetime | None = None
    confidence: float | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActionItemCreateRequest(BaseModel):
    """Request body for manually creating an action item.

    Attributes:
        meeting_id: Parent meeting identifier (required).
        description: What needs to be done (required).
        assigned_to_name: Display name of the assignee (required).
        assigned_to_user_id: Azure AD object ID of the assignee (optional).
        assigned_to_email: Email of the assignee (optional).
        deadline: Due date/time (optional).
        priority: Priority level -- high, medium, or low (optional, defaults to medium).
        source_quote: Transcript excerpt that prompted this item (optional).
    """

    meeting_id: uuid.UUID
    description: str
    assigned_to_name: str
    assigned_to_user_id: str | None = None
    assigned_to_email: str | None = None
    deadline: datetime | None = None
    priority: str = Field(
        default="medium",
        description="Priority level: high, medium, low",
    )
    source_quote: str | None = None


class ActionItemUpdateRequest(BaseModel):
    """Partial update (PATCH) schema for an action item.

    All fields are optional. Only supplied fields will be updated.

    Attributes:
        status: New status (pending, in_progress, completed, cancelled).
        priority: New priority (high, medium, low).
        deadline: Updated deadline (ISO 8601 datetime with timezone).
        assigned_to_name: Updated assignee display name.
        assigned_to_user_id: Updated assignee Azure AD object ID.
        assigned_to_email: Updated assignee email.
        description: Revised description of the task.
    """

    status: str | None = Field(
        default=None,
        description="New status: pending, in_progress, completed, cancelled",
    )
    priority: str | None = Field(
        default=None,
        description="New priority: high, medium, low",
    )
    deadline: datetime | None = Field(
        default=None,
        description="Updated deadline (ISO 8601 datetime with timezone)",
    )
    assigned_to_name: str | None = None
    assigned_to_user_id: str | None = None
    assigned_to_email: str | None = None
    description: str | None = None


class ActionItemUpdate(BaseModel):
    """Partial update schema for an action item (monolith-compatible alias).

    All fields are optional. Only the fields that are provided will be
    applied to the model.  Used by PATCH /action-items/{item_id} and by
    Adaptive Card submit actions.

    Attributes:
        status: New status (pending, in_progress, completed, snoozed).
        priority: New priority (high, medium, low).
        deadline: Updated deadline (ISO 8601 datetime with timezone).
        assigned_to_name: Updated assignee display name.
        assigned_to_user_id: Updated assignee Azure AD user ID.
        assigned_to_email: Updated assignee email address.
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
    assigned_to_name: str | None = None
    assigned_to_user_id: str | None = None
    assigned_to_email: str | None = None


class ActionItemListResponse(BaseModel):
    """Paginated response wrapper for listing action items.

    Attributes:
        items: List of action item response objects for the current page.
        total: Total number of action items matching the filter criteria.
    """

    items: list[ActionItemResponse]
    total: int = Field(
        description="Total number of action items matching the filter criteria"
    )
