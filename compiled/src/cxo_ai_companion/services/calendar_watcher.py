"""Calendar Watcher service -- enterprise edition.

Manages Microsoft Graph change notification subscriptions for user calendars
and processes incoming webhook notifications to detect, store, and schedule
bot joins for Teams meetings.

Ported from ``teams-meeting-assistant/app/services/calendar_watcher.py`` with:
- CXO exceptions (CalendarError)
- Structured logging from observability layer
- Session-factory pattern: each operation creates its own DB session
- Kept subscription lifecycle management
- Kept APScheduler integration for bot auto-join
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cxo_ai_companion.exceptions import CalendarError
from cxo_ai_companion.models.meeting import Meeting
from cxo_ai_companion.models.subscription import GraphSubscription, UserPreference
from cxo_ai_companion.observability import get_logger, trace_span
from cxo_ai_companion.security.context import SecurityContext, create_system_context

if TYPE_CHECKING:
    from cxo_ai_companion.services.graph_client import GraphClient

logger = get_logger("services.calendar_watcher")

# Regex to extract user_id and event_id from the Graph resource path
# e.g. "users/abc-123/events/def-456"
_RESOURCE_RE = re.compile(
    r"users/(?P<user_id>[^/]+)/events/(?P<event_id>[^/]+)"
)


class CalendarWatcher:
    """Watches opted-in user calendars via Graph subscriptions.

    Uses a session-factory pattern: each operation (setup, renew, webhook)
    creates its own short-lived DB session, avoiding stale-session issues
    from long-lived service instances stored in ``app.state``.
    """

    def __init__(
        self,
        graph_client: GraphClient,
        session_factory: async_sessionmaker[AsyncSession],
        scheduler: Any,  # APScheduler AsyncIOScheduler
        settings: Any,
        ctx: SecurityContext | None = None,
    ) -> None:
        self.graph = graph_client
        self._session_factory = session_factory
        self.scheduler = scheduler
        self.settings = settings
        self._ctx = ctx or create_system_context()

    # ------------------------------------------------------------------
    # Subscription Management
    # ------------------------------------------------------------------

    async def setup_subscriptions(self) -> None:
        """Create Graph calendar subscriptions for every opted-in user.

        Called once on application startup.
        """
        async with trace_span("calendar_watcher.setup_subscriptions"):
            async with self._session_factory() as db:
                result = await db.execute(
                    select(UserPreference).where(UserPreference.auto_join_enabled.is_(True))
                )
                opted_in_users = result.scalars().all()

                if not opted_in_users:
                    logger.info("No opted-in users found; skipping subscription setup")
                    return

                webhook_url = f"{self.settings.BASE_URL}/api/webhooks/graph"

                for user_pref in opted_in_users:
                    # Check whether we already have an active subscription for this user
                    existing = await db.execute(
                        select(GraphSubscription).where(
                            GraphSubscription.user_id == user_pref.user_id,
                            GraphSubscription.status == "active",
                        )
                    )
                    if existing.scalar_one_or_none() is not None:
                        logger.info(
                            "Active subscription already exists",
                            extra={"user_id": user_pref.user_id},
                        )
                        continue

                    try:
                        sub_data = await self.graph.create_subscription(
                            user_id=user_pref.user_id,
                            webhook_url=webhook_url,
                            ctx=self._ctx,
                        )

                        expiration = datetime.fromisoformat(
                            sub_data["expirationDateTime"].replace("Z", "+00:00")
                        )

                        subscription = GraphSubscription(
                            subscription_id=sub_data["id"],
                            user_id=user_pref.user_id,
                            resource=sub_data["resource"],
                            notification_url=webhook_url,
                            expiration=expiration,
                            status="active",
                        )
                        db.add(subscription)
                        await db.commit()

                        logger.info(
                            "Created subscription for user",
                            extra={
                                "user_id": user_pref.user_id,
                                "subscription_id": sub_data["id"],
                            },
                        )
                    except Exception as exc:
                        logger.exception(
                            "Failed to create subscription for user",
                            extra={"user_id": user_pref.user_id},
                        )
                        raise CalendarError(
                            message=f"Failed to create subscription for user {user_pref.user_id}",
                            subscription_id=None,
                            cause=exc,
                        ) from exc

    async def renew_subscriptions(self) -> None:
        """Renew Graph subscriptions that are expiring within 6 hours.

        Run periodically (every 12 hours) by APScheduler.
        """
        async with trace_span("calendar_watcher.renew_subscriptions"):
            async with self._session_factory() as db:
                threshold = datetime.now(timezone.utc) + timedelta(hours=6)
                result = await db.execute(
                    select(GraphSubscription).where(
                        GraphSubscription.status == "active",
                        GraphSubscription.expiration <= threshold,
                    )
                )
                expiring = result.scalars().all()

                if not expiring:
                    logger.info("No subscriptions need renewal")
                    return

                webhook_url = f"{self.settings.BASE_URL}/api/webhooks/graph"

                for sub in expiring:
                    new_expiration = datetime.now(timezone.utc) + timedelta(days=3)
                    try:
                        await self.graph.renew_subscription(
                            subscription_id=sub.subscription_id,
                            new_expiration=new_expiration,
                            ctx=self._ctx,
                        )
                        sub.expiration = new_expiration
                        await db.commit()
                        logger.info(
                            "Renewed subscription",
                            extra={
                                "subscription_id": sub.subscription_id,
                                "user_id": sub.user_id,
                                "new_expiration": new_expiration.isoformat(),
                            },
                        )
                    except Exception:
                        logger.exception(
                            "Failed to renew subscription -- recreating",
                            extra={"subscription_id": sub.subscription_id},
                        )
                        sub.status = "failed"
                        await db.commit()

                        # Attempt to create a fresh subscription
                        try:
                            sub_data = await self.graph.create_subscription(
                                user_id=sub.user_id,
                                webhook_url=webhook_url,
                                ctx=self._ctx,
                            )
                            expiration = datetime.fromisoformat(
                                sub_data["expirationDateTime"].replace("Z", "+00:00")
                            )
                            new_sub = GraphSubscription(
                                subscription_id=sub_data["id"],
                                user_id=sub.user_id,
                                resource=sub_data["resource"],
                                notification_url=webhook_url,
                                expiration=expiration,
                                status="active",
                            )
                            db.add(new_sub)
                            await db.commit()
                            logger.info(
                                "Recreated subscription after renewal failure",
                                extra={
                                    "user_id": sub.user_id,
                                    "new_subscription_id": sub_data["id"],
                                },
                            )
                        except Exception:
                            logger.exception(
                                "Failed to recreate subscription",
                                extra={"user_id": sub.user_id},
                            )

    # ------------------------------------------------------------------
    # Webhook Processing
    # ------------------------------------------------------------------

    async def handle_webhook(self, notification: dict[str, Any]) -> None:
        """Process a single Graph change notification.

        Called from the webhook route for each validated notification.
        Creates its own DB session to avoid stale-session issues.
        """
        async with trace_span("calendar_watcher.handle_webhook"):
            async with self._session_factory() as db:
                try:
                    await self._process_notification(db, notification)
                except Exception:
                    logger.exception(
                        "Error processing notification",
                        extra={
                            "subscription_id": notification.get("subscriptionId"),
                            "change_type": notification.get("changeType"),
                            "resource": notification.get("resource"),
                        },
                    )

    async def _process_notification(
        self, db: AsyncSession, notification: dict[str, Any]
    ) -> None:
        """Handle a single Graph change notification."""
        resource = notification.get("resource", "")
        change_type = notification.get("changeType", "")

        match = _RESOURCE_RE.search(resource)
        if not match:
            logger.warning(
                "Could not parse resource path",
                extra={"resource": resource},
            )
            return

        user_id = match.group("user_id")
        event_id = match.group("event_id")

        if change_type == "deleted":
            await self._handle_deleted(db, event_id)
            return

        # For created / updated we need full event details
        event = await self.graph.get_event(
            user_id=user_id, event_id=event_id, ctx=self._ctx,
        )

        # Only process Teams meetings (events with an online meeting join URL)
        join_url = (event.get("onlineMeeting") or {}).get("joinUrl")
        if not join_url and not event.get("isOnlineMeeting"):
            logger.debug(
                "Skipping non-Teams-meeting event",
                extra={"event_id": event_id, "subject": event.get("subject")},
            )
            return

        if change_type == "created":
            await self._handle_created(db, event, user_id, join_url)
        elif change_type == "updated":
            await self._handle_updated(db, event, user_id, join_url)

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------

    async def _handle_created(
        self, db: AsyncSession, event: dict[str, Any], user_id: str, join_url: str | None
    ) -> None:
        """Store a newly-created Teams meeting and schedule a bot join."""
        event_id = event["id"]

        # Avoid duplicate meetings
        existing = await db.execute(
            select(Meeting).where(Meeting.teams_meeting_id == event_id)
        )
        if existing.scalar_one_or_none() is not None:
            logger.info(
                "Meeting already exists -- skipping",
                extra={"event_id": event_id},
            )
            return

        scheduled_start = _parse_graph_datetime(event["start"])
        scheduled_end = _parse_graph_datetime(event["end"])

        organizer_info = event.get("organizer", {}).get("emailAddress", {})
        online_meeting = event.get("onlineMeeting") or {}
        teams_meeting_id = online_meeting.get("joinMeetingIdSettings", {}).get(
            "joinMeetingId", event_id
        )
        thread_id = _extract_thread_id(join_url or "")

        meeting = Meeting(
            teams_meeting_id=teams_meeting_id,
            thread_id=thread_id,
            join_url=join_url or "",
            subject=event.get("subject", "Untitled Meeting"),
            organizer_id=user_id,
            organizer_name=organizer_info.get("name", "Unknown"),
            organizer_email=organizer_info.get("address", ""),
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            status="scheduled",
        )
        db.add(meeting)
        await db.commit()
        await db.refresh(meeting)

        logger.info(
            "Stored new meeting",
            extra={
                "meeting_id": str(meeting.id),
                "subject": meeting.subject,
                "scheduled_start": meeting.scheduled_start.isoformat(),
            },
        )

        await self.schedule_bot_join(meeting)

    async def _handle_updated(
        self, db: AsyncSession, event: dict[str, Any], user_id: str, join_url: str | None
    ) -> None:
        """Update an existing meeting and reschedule the bot join if needed."""
        event_id = event["id"]

        result = await db.execute(
            select(Meeting).where(Meeting.teams_meeting_id == event_id)
        )
        meeting = result.scalar_one_or_none()

        if meeting is None:
            # The update is for a meeting we haven't seen -- treat as created
            await self._handle_created(db, event, user_id, join_url)
            return

        new_start = _parse_graph_datetime(event["start"])
        new_end = _parse_graph_datetime(event["end"])
        time_changed = (
            meeting.scheduled_start != new_start
            or meeting.scheduled_end != new_end
        )

        # Update fields
        meeting.subject = event.get("subject", meeting.subject)
        meeting.scheduled_start = new_start
        meeting.scheduled_end = new_end
        if join_url:
            meeting.join_url = join_url
            meeting.thread_id = _extract_thread_id(join_url)

        organizer_info = event.get("organizer", {}).get("emailAddress", {})
        if organizer_info.get("name"):
            meeting.organizer_name = organizer_info["name"]
        if organizer_info.get("address"):
            meeting.organizer_email = organizer_info["address"]

        await db.commit()

        logger.info(
            "Updated meeting",
            extra={
                "meeting_id": str(meeting.id),
                "time_changed": time_changed,
            },
        )

        if time_changed and meeting.status == "scheduled":
            # Remove old scheduled job and reschedule
            job_id = f"join_{meeting.id}"
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass  # Job may not exist
            await self.schedule_bot_join(meeting)

    async def _handle_deleted(self, db: AsyncSession, event_id: str) -> None:
        """Cancel a scheduled bot join and mark the meeting as cancelled."""
        result = await db.execute(
            select(Meeting).where(Meeting.teams_meeting_id == event_id)
        )
        meeting = result.scalar_one_or_none()
        if meeting is None:
            logger.debug(
                "Deleted event not found in DB",
                extra={"event_id": event_id},
            )
            return

        meeting.status = "cancelled"
        await db.commit()

        # Cancel the scheduled join job
        job_id = f"join_{meeting.id}"
        try:
            self.scheduler.remove_job(job_id)
            logger.info(
                "Cancelled scheduled bot join",
                extra={"meeting_id": str(meeting.id)},
            )
        except Exception:
            logger.debug(
                "No scheduled job to cancel",
                extra={"meeting_id": str(meeting.id)},
            )

    # ------------------------------------------------------------------
    # Bot Join Scheduling
    # ------------------------------------------------------------------

    async def schedule_bot_join(self, meeting: Meeting) -> None:
        """Schedule the ACS bot to join the meeting before its start time.

        Uses APScheduler to add a one-time ``date`` trigger job that fires
        ``BOT_JOIN_BEFORE_MINUTES`` minutes before ``meeting.scheduled_start``.

        If the join time is already in the past, the job runs immediately.
        """
        join_time = meeting.scheduled_start - timedelta(
            minutes=self.settings.BOT_JOIN_BEFORE_MINUTES
        )

        now = datetime.now(timezone.utc)
        if join_time < now:
            # Meeting is imminent or already started -- join ASAP
            join_time = now + timedelta(seconds=5)

        job_id = f"join_{meeting.id}"

        self.scheduler.add_job(
            _execute_bot_join,
            trigger="date",
            run_date=join_time,
            id=job_id,
            replace_existing=True,
            kwargs={"meeting_id": str(meeting.id)},
        )

        logger.info(
            "Scheduled bot join",
            extra={
                "meeting_id": str(meeting.id),
                "join_time": join_time.isoformat(),
                "subject": meeting.subject,
            },
        )


# ======================================================================
# Module-level helpers
# ======================================================================


def _parse_graph_datetime(dt_dict: dict[str, Any]) -> datetime:
    """Parse a Graph ``dateTimeTimeZone`` resource into a timezone-aware datetime."""
    raw = dt_dict.get("dateTime", "")
    tz_name = dt_dict.get("timeZone", "UTC")

    if tz_name == "UTC":
        if "." in raw:
            base, frac = raw.split(".")
            frac = frac[:6]
            raw = f"{base}.{frac}"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _extract_thread_id(join_url: str) -> str:
    """Extract the Teams chat thread ID from a meeting join URL."""
    from urllib.parse import unquote

    match = re.search(r"meetup-join/([^/]+)", join_url)
    if match:
        return unquote(match.group(1))
    return join_url


async def _execute_bot_join(meeting_id: str) -> None:
    """APScheduler job function that joins a meeting via ACS.

    Creates a fresh DB session factory reference to avoid stale session issues.
    Delegates status checks and DB operations to ACSCallService.join_meeting().
    """
    logger.info("Executing scheduled bot join", extra={"meeting_id": meeting_id})

    from cxo_ai_companion.dependencies import get_settings, get_session_factory
    from cxo_ai_companion.services.acs_call_service import ACSCallService

    try:
        settings = get_settings()
        session_factory = get_session_factory()
    except Exception:
        logger.exception(
            "Could not initialize for scheduled bot join",
            extra={"meeting_id": meeting_id},
        )
        return

    try:
        meeting_uuid = uuid.UUID(meeting_id)
    except ValueError:
        logger.error("Invalid meeting_id format: %s", meeting_id)
        return

    acs_service = ACSCallService(settings, session_factory)
    try:
        call_connection_id = await acs_service.join_meeting(meeting_uuid)
        if call_connection_id:
            logger.info(
                "Bot joined meeting %s, call_connection_id=%s",
                meeting_id,
                call_connection_id,
            )
    except Exception:
        logger.exception(
            "Failed to join meeting %s via ACS",
            meeting_id,
        )
