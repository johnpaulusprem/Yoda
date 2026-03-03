"""Project CRUD API routes."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from cxo_ai_companion.dependencies import get_db
from cxo_ai_companion.security.auth_dependency import get_current_user
from cxo_ai_companion.security.context import SecurityContext
from cxo_ai_companion.data_access.repositories.project_repository import ProjectRepository
from cxo_ai_companion.data_access.repositories import MeetingRepository
from cxo_ai_companion.models.project import Project, project_meetings_table
from cxo_ai_companion.schemas.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    status: str | None = Query(None),
    owner: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """List projects with optional filters."""
    repo = ProjectRepository(db)
    if owner:
        projects = await repo.get_by_owner(owner)
    elif status:
        projects = await repo.find_by(status=status)
    else:
        projects = await repo.get_all(limit, offset)
    total = len(projects)
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in projects],
        total=total,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID, db: AsyncSession = Depends(get_db), ctx: SecurityContext = Depends(get_current_user)):
    """Get a project with its linked meetings."""
    repo = ProjectRepository(db)
    project = await repo.get_with_meetings(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Create a new project."""
    repo = ProjectRepository(db)
    project = Project(
        name=body.name,
        owner_user_id=body.owner_user_id,
        description=body.description,
        target_date=body.target_date,
        current_phase=body.current_phase,
    )
    created = await repo.create(project)
    return ProjectResponse.model_validate(created)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdateRequest,
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Partially update a project."""
    repo = ProjectRepository(db)
    project = await repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)
    updated = await repo.update(project)
    return ProjectResponse.model_validate(updated)


@router.post("/{project_id}/meetings/{meeting_id}", status_code=201)
async def link_meeting_to_project(
    project_id: UUID,
    meeting_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Link a meeting to a project."""
    p_repo = ProjectRepository(db)
    project = await p_repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    m_repo = MeetingRepository(db)
    meeting = await m_repo.get_by_id(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    await db.execute(
        project_meetings_table.insert().values(
            project_id=project_id, meeting_id=meeting_id
        )
    )
    await db.flush()
    return {"status": "linked", "project_id": str(project_id), "meeting_id": str(meeting_id)}


@router.delete("/{project_id}/meetings/{meeting_id}")
async def unlink_meeting_from_project(
    project_id: UUID,
    meeting_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: SecurityContext = Depends(get_current_user),
):
    """Unlink a meeting from a project."""
    await db.execute(
        project_meetings_table.delete().where(
            project_meetings_table.c.project_id == project_id,
            project_meetings_table.c.meeting_id == meeting_id,
        )
    )
    await db.flush()
    return {"status": "unlinked", "project_id": str(project_id), "meeting_id": str(meeting_id)}
