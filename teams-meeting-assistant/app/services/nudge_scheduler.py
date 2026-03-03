import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models.action_item import ActionItem
from app.models.meeting import Meeting
from app.services.delivery import DeliveryService

logger = logging.getLogger(__name__)

# Minimum interval between nudges for the same item (hours)
NUDGE_COOLDOWN_HOURS = 4

# How close to the deadline before we start nudging (hours)
DEADLINE_PROXIMITY_HOURS = 24


class NudgeScheduler:
    """Runs periodically to check for action items that need nudging.

    Scheduled via APScheduler to run every NUDGE_CHECK_INTERVAL_MINUTES
    (default: 30 minutes). Queries for action items that are approaching
    or past their deadline and sends nudge reminders or escalations.
    """

    def __init__(
        self,
        delivery: DeliveryService,
        db: AsyncSession,
        settings: Settings,
    ):
        self.delivery = delivery
        self.db = db
        self.settings = settings

    async def run(self) -> None:
        """Main scheduler tick. Called by APScheduler or Celery beat.

        Logic:
        1. Query action items where:
           - status is "pending" or "in_progress"
           - AND (deadline is within 24 hours OR deadline has passed)
           - AND (last_nudged_at is NULL or last_nudged_at > 4 hours ago)
           - AND (snoozed_until is NULL or snoozed_until < now)
        2. For each item:
           a. If nudge_count >= NUDGE_ESCALATION_THRESHOLD: send escalation
           b. Else: send nudge to assignee
        3. Update nudge tracking fields
        4. Commit all changes
        """
        now = datetime.now(timezone.utc)
        deadline_threshold = now + timedelta(hours=DEADLINE_PROXIMITY_HOURS)
        nudge_cooldown = now - timedelta(hours=NUDGE_COOLDOWN_HOURS)

        logger.info(
            "Nudge scheduler tick at %s, checking items with deadline "
            "before %s",
            now.isoformat(),
            deadline_threshold.isoformat(),
        )

        try:
            # Build the query for nudge-eligible action items
            stmt = (
                select(ActionItem)
                .options(selectinload(ActionItem.meeting))
                .where(
                    # Status must be pending or in_progress
                    ActionItem.status.in_(["pending", "in_progress"]),
                    # Deadline exists and is within 24 hours or already passed
                    ActionItem.deadline.isnot(None),
                    ActionItem.deadline <= deadline_threshold,
                    # Not recently nudged (cooldown period)
                    or_(
                        ActionItem.last_nudged_at.is_(None),
                        ActionItem.last_nudged_at < nudge_cooldown,
                    ),
                    # Not currently snoozed
                    or_(
                        ActionItem.snoozed_until.is_(None),
                        ActionItem.snoozed_until < now,
                    ),
                )
            )

            result = await self.db.execute(stmt)
            items = result.scalars().all()

            logger.info("Found %d action items eligible for nudging", len(items))

            nudge_count = 0
            escalation_count = 0
            error_count = 0

            for item in items:
                try:
                    # Clear snooze if it has expired
                    if (
                        item.snoozed_until is not None
                        and item.snoozed_until < now
                    ):
                        item.snoozed_until = None

                    escalation_threshold = (
                        self.settings.NUDGE_ESCALATION_THRESHOLD
                    )

                    if item.nudge_count >= escalation_threshold:
                        # Escalate to meeting organizer
                        meeting = item.meeting
                        if meeting is None:
                            logger.warning(
                                "Action item %s has no associated meeting, "
                                "skipping escalation",
                                item.id,
                            )
                            continue

                        await self.delivery.send_escalation(item, meeting)
                        escalation_count += 1
                        logger.info(
                            "Escalated action item %s (nudge count: %d, "
                            "threshold: %d)",
                            item.id,
                            item.nudge_count,
                            escalation_threshold,
                        )
                    else:
                        # Send nudge to the assignee
                        await self.delivery.send_nudge(item)
                        nudge_count += 1

                except Exception:
                    error_count += 1
                    logger.exception(
                        "Failed to process nudge for action item %s",
                        item.id,
                    )

            # Commit all nudge tracking updates in a single transaction
            await self.db.commit()

            logger.info(
                "Nudge scheduler tick complete: %d nudges sent, "
                "%d escalations sent, %d errors",
                nudge_count,
                escalation_count,
                error_count,
            )

        except Exception:
            logger.exception("Nudge scheduler tick failed")
            await self.db.rollback()
