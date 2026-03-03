"""Wireframe gap closure -- notifications, projects, and extended columns.

Revision ID: 002_wireframe
Revises: 001_pgvector
Create Date: 2026-03-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002_wireframe"
down_revision = "001_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- notifications table --
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.String(), nullable=False, index=True),
        sa.Column("type", sa.String(), nullable=False, comment="summary_ready|action_assigned|action_overdue|document_shared|meeting_reminder|conflict_detected"),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("related_entity_type", sa.String(), nullable=True),
        sa.Column("related_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # -- projects table --
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active", comment="active|on_hold|completed"),
        sa.Column("completion_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("current_phase", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # -- project_meetings association table --
    op.create_table(
        "project_meetings",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True),
    )

    # -- Add columns to existing tables --
    op.add_column("action_items", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("documents", sa.Column("review_status", sa.String(), nullable=True, server_default="none"))


def downgrade() -> None:
    op.drop_column("documents", "review_status")
    op.drop_column("action_items", "confidence")
    op.drop_table("project_meetings")
    op.drop_table("projects")
    op.drop_table("notifications")
