"""add_transcript_unique_and_speaker_events

Revision ID: dce9f1c93191
Revises: a3b4c5d6e7f8
Create Date: 2026-04-02

1. Add unique constraint on transcript_segments(meeting_id, sequence_number)
   so retransmitted batches are idempotent.
2. Create speaker_events table for browser-bot SPEAKER_START/SPEAKER_END events.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'dce9f1c93191'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Unique constraint for transcript deduplication
    op.create_unique_constraint(
        "uq_transcript_meeting_sequence",
        "transcript_segments",
        ["meeting_id", "sequence_number"],
    )

    # 2. Speaker events table
    op.create_table(
        "speaker_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("bot_instance_id", sa.String(256), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),  # SPEAKER_START or SPEAKER_END
        sa.Column("participant_id", sa.String(256), nullable=False),
        sa.Column("participant_name", sa.String(512), nullable=True),
        sa.Column("relative_timestamp_ms", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("speaker_events")
    op.drop_constraint("uq_transcript_meeting_sequence", "transcript_segments", type_="unique")
