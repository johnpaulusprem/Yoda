"""add source column to transcript_segments

Revision ID: a3b4c5d6e7f8
Revises: d219333367e1
Create Date: 2026-03-27

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a3b4c5d6e7f8"
down_revision = "d219333367e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transcript_segments", sa.Column("source", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("transcript_segments", "source")
