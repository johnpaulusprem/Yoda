"""Nudge Scheduler service -- enterprise edition.

Runs periodically to check for action items that need nudging. Queries for
action items that are approaching or past their deadline and sends nudge
reminders or escalations.

Ported from ``teams-meeting-assistant/app/services/nudge_scheduler.py`` with:
- CXO exceptions
- Structured logging from observability layer
- Kept cooldown logic, escalation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cxo_ai_companion.exceptions import DeliveryError
from cxo_ai_companion.models.action_item import ActionItem
from cxo_ai_companion.models.meeting import Meeting
from cxo_ai_companion.observability import get_logger, trace_span
from cxo_ai_companion.services.delivery import DeliveryService

logger = get_logger("services.nudge_scheduler")

# Minimum interval between nudges for the same item (hours)
NUDGE_COOLDOWN_HOURS = 4

# How close to the deadline before we start nudging (hours)
DEADLINE_PROXIMITY_HOURS = 24


class NudgeScheduler:
    """Runs periodically to check for action items that need nudging.

    Scheduled via APScheduler to run every ``NUDGE_CHECK_INTERVAL_MINUTES``
    (default: 30 minutes). Queries for action items that are approaching
    or past their deadline and sends nudge reminders or escalations.
    """

    def __init__(
        self,
        delivery: DeliveryService,
        db: AsyncSession,
        settings: Any,
    ) -> None:
        """Initialize the nudge scheduler.

        Args:
            delivery: DeliveryService for sending nudge and escalation cards.
            db: Async SQLAlchemy session for querying action items.
            settings: Application settings (NUDGE_ESCALATION_THRESHOLD).
        """
        self.delivery = delivery
        self.db = db
        self.settings = settings

    async def run(self) -> None:
        """Execute a nudge scheduler tick. Called by APScheduler or Celery beat.

        Queries for action items approaching or past their deadline with
        cooldown and snooze checks, then sends nudge reminders or escalates
        to the meeting organizer after too many missed nudges.

        Raises:
            No exceptions propagated; failures are logged and the
            transaction is rolled back.
        """
        async with trace_span("nudge_scheduler.run"):
            now = datetime.now(timezone.utc)
            deadline_threshold = now + timedelta(hours=DEADLINE_PROXIMITY_HOURS)
            nudge_cooldown = now - timedelta(hours=NUDGE_COOLDOWN_HOURS)

            logger.info(
                "Nudge scheduler tick at %s, checking items with deadline before %s",
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
                            ActionItem.last_nudge_at.is_(None),
                            ActionItem.last_nudge_at < nudge_cooldown,
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

                    except DeliveryError:
                        error_count += 1
                        logger.exception(
                            "Delivery error processing nudge for action item %s",
                            item.id,
                        )
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
