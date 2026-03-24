"""Post-processing pipeline service.

After a meeting ends (detected via Browser Bot lifecycle event),
this service assembles the transcript, runs AI processing, resolves action-item
owners, and delivers the summary.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from yoda_foundation.models.meeting import Meeting

if TYPE_CHECKING:
    from meeting_service.services.ai_processor import AIProcessor
    from meeting_service.services.delivery import DeliveryService
    from meeting_service.services.owner_resolver import OwnerResolver

logger = logging.getLogger(__name__)


class PostProcessingService:
    """Runs the AI processing pipeline after a meeting completes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.ai_processor: AIProcessor | None = None
        self.delivery_service: DeliveryService | None = None
        self.owner_resolver: OwnerResolver | None = None

    async def run(self, meeting_id: uuid.UUID) -> None:
        """Assemble transcript, run AI processing, and deliver the summary.

        This is executed as a background task after a meeting ends.
        Creates a fresh DB session per invocation to avoid stale state.
        """
        logger.info("Starting post-processing for meeting %s", meeting_id)

        async with self._session_factory() as db:
            try:
                stmt = (
                    select(Meeting)
                    .where(Meeting.id == meeting_id)
                    .options(
                        selectinload(Meeting.transcript_segments),
                        selectinload(Meeting.participants),
                    )
                )
                result = await db.execute(stmt)
                meeting = result.scalar_one_or_none()
                if meeting is None:
                    logger.error(
                        "Post-processing: meeting %s not found", meeting_id
                    )
                    return

                segments = sorted(
                    meeting.transcript_segments, key=lambda s: s.sequence_number
                )

                if not segments:
                    logger.warning(
                        "Post-processing: no transcript segments for meeting %s",
                        meeting_id,
                    )
                    return

                logger.info(
                    "Post-processing meeting %s: %d transcript segments",
                    meeting_id,
                    len(segments),
                )

                # ----- Step 1: AI processing -----
                if self.ai_processor is None:
                    logger.error(
                        "Post-processing: ai_processor not attached"
                    )
                    return

                ai_result = await self.ai_processor.process_meeting(
                    meeting=meeting,
                    transcript_segments=segments,
                )

                # ----- Step 2: Resolve action-item owners -----
                if self.owner_resolver is not None:
                    action_items = ai_result.get("action_items", [])
                    for item_record in action_items:
                        assigned_name = (
                            item_record.assigned_to_name
                            if hasattr(item_record, "assigned_to_name")
                            else item_record.get("assigned_to_name", "")
                        )
                        if assigned_name:
                            user_id, email = await self.owner_resolver.resolve(
                                assigned_name, meeting.participants
                            )
                            if hasattr(item_record, "assigned_to_user_id"):
                                item_record.assigned_to_user_id = user_id
                                item_record.assigned_to_email = email
                            else:
                                item_record["assigned_to_user_id"] = user_id
                                item_record["assigned_to_email"] = email

                # ----- Step 3: Deliver summary -----
                if self.delivery_service is not None:
                    summary = ai_result.get("summary")
                    action_items_list = ai_result.get("action_items", [])
                    if summary is not None:
                        await self.delivery_service.deliver_summary(
                            meeting=meeting,
                            summary=summary,
                            action_items=action_items_list,
                        )
                        logger.info(
                            "Summary delivered for meeting %s", meeting_id
                        )
                else:
                    logger.warning(
                        "Post-processing: delivery_service not attached; skipping delivery"
                    )

                logger.info("Post-processing completed for meeting %s", meeting_id)

            except Exception:
                logger.exception(
                    "Post-processing failed for meeting %s", meeting_id
                )
                try:
                    stmt = select(Meeting).where(Meeting.id == meeting_id)
                    result = await db.execute(stmt)
                    meeting = result.scalar_one_or_none()
                    if meeting is not None:
                        meeting.status = "failed"
                        db.add(meeting)
                        await db.commit()
                except Exception:
                    logger.exception(
                        "Failed to mark meeting %s as failed", meeting_id
                    )
