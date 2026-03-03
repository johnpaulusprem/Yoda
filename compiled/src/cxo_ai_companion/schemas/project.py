"""Pydantic v2 schemas for projects."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectResponse(BaseModel):
    """API response schema for a project entity.

    Serialized from the Project ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique project identifier (UUID).
        name: Project name.
        description: Detailed project description.
        owner_user_id: Azure AD object ID of the project owner.
        status: Current status (active, on_hold, completed).
        completion_pct: Completion percentage (0.0--100.0).
        target_date: Target completion date.
        current_phase: Current project phase label.
        created_at: Record creation timestamp.
        updated_at: Record last-update timestamp.
    """

    id: uuid.UUID
    name: str
    description: str | None = None
    owner_user_id: str
    status: str = "active"
    completion_pct: float = 0.0
    target_date: date | None = None
    current_phase: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectCreateRequest(BaseModel):
    """Request body for creating a new project.

    Attributes:
        name: Project name (required).
        owner_user_id: Azure AD object ID of the project owner (required).
        description: Detailed project description (optional).
        target_date: Target completion date (optional).
        current_phase: Initial project phase label (optional).
    """

    name: str
    owner_user_id: str
    description: str | None = None
    target_date: date | None = None
    current_phase: str | None = None


class ProjectUpdateRequest(BaseModel):
    """Partial update (PATCH) schema for a project.

    All fields are optional. Only supplied fields will be updated.

    Attributes:
        name: Updated project name.
        description: Updated project description.
        status: New status (active, on_hold, completed).
        completion_pct: Updated completion percentage.
        target_date: Updated target completion date.
        current_phase: Updated project phase label.
    """

    name: str | None = None
    description: str | None = None
    status: str | None = Field(
        default=None,
        description="New status: active, on_hold, completed",
    )
    completion_pct: float | None = None
    target_date: date | None = None
    current_phase: str | None = None


class ProjectListResponse(BaseModel):
    """Paginated response wrapper for listing projects.

    Attributes:
        items: List of project response objects for the current page.
        total: Total number of projects matching the query.
    """

    items: list[ProjectResponse]
    total: int
