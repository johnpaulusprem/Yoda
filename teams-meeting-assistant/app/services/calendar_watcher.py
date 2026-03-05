"""Calendar Watcher service.

Manages Microsoft Graph change notification subscriptions for user calendars
and processes incoming webhook notifications to detect, store, and schedule
bot joins for Teams meetings.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.meeting import Meeting
from app.models.subscription import GraphSubscription, UserPreference
from app.schemas.webhook import GraphChangeNotification, GraphWebhookPayload
from app.services.graph_client import GraphClient

logger = logging.getLogger(__name__)

# Regex to extract user_id and event_id from the Graph resource path
# e.g. "users/abc-123/events/def-456"
_RESOURCE_RE = re.compile(
    r"users/(?P<user_id>[^/]+)/events/(?P<event_id>[^/]+)"
)


class CalendarWatcher:
    """Watches opted-in user calendars via Graph subscriptions.

    Responsibilities:
    - Create / renew / delete Graph change notification subscriptions.
    - Process incoming webhook payloads (created / updated / deleted events).
    - Store detected Teams meetings in the database.
    - Schedule APScheduler jobs so the ACS bot joins before each meeting.
    """

    def __init__(
        self,
        graph_client: GraphClient,
        db: AsyncSession,
        scheduler,  # APScheduler AsyncIOScheduler
        settings: Settings,
    ) -> None:
        self.graph = graph_client
        self.db = db
        self.scheduler = scheduler
        self.settings = settings

    # ------------------------------------------------------------------
    # Subscription Management
    # ------------------------------------------------------------------

    async def setup_subscriptions(self) -> None:
        """Create Graph calendar subscriptions for every opted-in user.

        Called once on application startup.  For each opted-in user that does
        not yet have an active subscription, we create a new one via the
        Graph API and persist it in the ``graph_subscriptions`` table.
        """
        result = await self.db.execute(
            select(UserPreference).where(UserPreference.opted_in.is_(True))
        )
        opted_in_users = result.scalars().all()

        if not opted_in_users:
            logger.info("No opted-in users found; skipping subscription setup")
            return

        webhook_url = f"{self.settings.BASE_URL}/webhooks/graph"

        for user_pref in opted_in_users:
            # Check whether we already have an active subscription for this user
            existing = await self.db.execute(
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
                sub_data = await self.graph.create_calendar_subscription(
                    user_id=user_pref.user_id,
                    webhook_url=webhook_url,
                )

                expiration = datetime.fromisoformat(
                    sub_data["expirationDateTime"].replace("Z", "+00:00")
                )

                subscription = GraphSubscription(
                    subscription_id=sub_data["id"],
                    user_id=user_pref.user_id,
                    resource=sub_data["resource"],
                    expiration=expiration,
                    status="active",
                )
                self.db.add(subscription)
                await self.db.commit()

                logger.info(
                    "Created subscription for user",
                    extra={
                        "user_id": user_pref.user_id,
                        "subscription_id": sub_data["id"],
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to create subscription for user",
                    extra={"user_id": user_pref.user_id},
                )

    async def renew_subscriptions(self) -> None:
        """Renew Graph subscriptions that are expiring within 6 hours.

        This is run periodically (every 12 hours) by APScheduler.
        If renewal fails, the old subscription is marked ``failed`` and a
        brand-new subscription is created.
        """
        threshold = datetime.now(timezone.utc) + timedelta(hours=6)
        result = await self.db.execute(
            select(GraphSubscription).where(
                GraphSubscription.status == "active",
                GraphSubscription.expiration <= threshold,
            )
        )
        expiring = result.scalars().all()

        if not expiring:
            logger.info("No subscriptions need renewal")
            return

        webhook_url = f"{self.settings.BASE_URL}/webhooks/graph"

        for sub in expiring:
            new_expiration = datetime.now(timezone.utc) + timedelta(days=3)
            try:
                await self.graph.renew_subscription(
                    subscription_id=sub.subscription_id,
                    new_expiration=new_expiration,
                )
                sub.expiration = new_expiration
                await self.db.commit()
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
                    "Failed to renew subscription — recreating",
                    extra={"subscription_id": sub.subscription_id},
                )
                sub.status = "failed"
                await self.db.commit()

                # Attempt to create a fresh subscription
                try:
                    sub_data = await self.graph.create_calendar_subscription(
                        user_id=sub.user_id,
                        webhook_url=webhook_url,
                    )
                    expiration = datetime.fromisoformat(
                        sub_data["expirationDateTime"].replace("Z", "+00:00")
                    )
                    new_sub = GraphSubscription(
                        subscription_id=sub_data["id"],
                        user_id=sub.user_id,
                        resource=sub_data["resource"],
                        expiration=expiration,
                        status="active",
                    )
                    self.db.add(new_sub)
                    await self.db.commit()
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

    async def handle_webhook(self, payload: dict) -> None:
        """Process a Graph change notification webhook payload.

        Called in a FastAPI ``BackgroundTask`` so the HTTP response is
        returned within 3 seconds (Graph requirement).

        Steps for each notification:
        1. Extract ``user_id`` and ``event_id`` from the resource path.
        2. Fetch full event details from Graph.
        3. Skip events that are not Teams meetings (no ``joinWebUrl``).
        4. For ``created`` — store the meeting and schedule a bot join.
        5. For ``updated`` — update meeting details; reschedule if the
           start time changed.
        6. For ``deleted`` — cancel the scheduled join and mark the
           meeting as cancelled.

        Args:
            payload: Raw JSON dict from the Graph webhook POST body.
        """
        parsed = GraphWebhookPayload.model_validate(payload)

        for notification in parsed.value:
            try:
                await self._process_notification(notification)
            except Exception:
                logger.exception(
                    "Error processing notification",
                    extra={
                        "subscription_id": notification.subscription_id,
                        "change_type": notification.change_type,
                        "resource": notification.resource,
                    },
                )

    async def _process_notification(
        self, notification: GraphChangeNotification
    ) -> None:
        """Handle a single Graph change notification."""
        match = _RESOURCE_RE.search(notification.resource)
        if not match:
            logger.warning(
                "Could not parse resource path",
                extra={"resource": notification.resource},
            )
            return

        user_id = match.group("user_id")
        event_id = match.group("event_id")

        change_type = notification.change_type

        if change_type == "deleted":
            await self._handle_deleted(event_id)
            return

        # For created / updated we need full event details
        event = await self.graph.get_event(user_id=user_id, event_id=event_id)

        # Only process Teams meetings (events with an online meeting join URL)
        join_url = (event.get("onlineMeeting") or {}).get("joinUrl")
        if not join_url and not event.get("isOnlineMeeting"):
            logger.debug(
                "Skipping non-Teams-meeting event",
                extra={"event_id": event_id, "subject": event.get("subject")},
            )
            return

        if change_type == "created":
            await self._handle_created(event, user_id, join_url)
        elif change_type == "updated":
            await self._handle_updated(event, user_id, join_url)

    # ------------------------------------------------------------------
    # Notification handlers
    # ------------------------------------------------------------------

    async def _handle_created(
        self, event: dict, user_id: str, join_url: str | None
    ) -> None:
        """Store a newly-created Teams meeting and schedule a bot join."""
        event_id = event["id"]

        # Avoid duplicate meetings
        existing = await self.db.execute(
            select(Meeting).where(Meeting.teams_meeting_id == event_id)
        )
        if existing.scalar_one_or_none() is not None:
            logger.info(
                "Meeting already exists — skipping",
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
        self.db.add(meeting)
        await self.db.commit()
        await self.db.refresh(meeting)

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
        self, event: dict, user_id: str, join_url: str | None
    ) -> None:
        """Update an existing meeting and reschedule the bot join if needed."""
        event_id = event["id"]

        result = await self.db.execute(
            select(Meeting).where(Meeting.teams_meeting_id == event_id)
        )
        meeting = result.scalar_one_or_none()

        if meeting is None:
            # The update is for a meeting we haven't seen — treat as created
            await self._handle_created(event, user_id, join_url)
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

        await self.db.commit()

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

    async def _handle_deleted(self, event_id: str) -> None:
        """Cancel a scheduled bot join and mark the meeting as cancelled."""
        result = await self.db.execute(
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
        await self.db.commit()

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

        If the join time is already in the past (meeting is about to start
        or has started), the job is scheduled to run immediately.

        The scheduled job invokes ``acs_call_service.join_meeting`` at runtime
        by importing it and creating a fresh DB session so it is not coupled
        to the startup session.

        Args:
            meeting: The Meeting model instance to schedule a join for.
        """
        scheduled = meeting.scheduled_start
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        join_time = scheduled - timedelta(
            minutes=self.settings.BOT_JOIN_BEFORE_MINUTES
        )

        now = datetime.now(timezone.utc)
        if join_time < now:
            # Meeting is imminent or already started — join ASAP
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


def _parse_graph_datetime(dt_dict: dict) -> datetime:
    """Parse a Graph ``dateTimeTimeZone`` resource into a timezone-aware datetime.

    Graph returns event start/end as::

        {"dateTime": "2026-03-04T10:00:00.0000000", "timeZone": "UTC"}

    Args:
        dt_dict: The ``start`` or ``end`` dict from a Graph event.

    Returns:
        A timezone-aware ``datetime`` in UTC.
    """
    raw = dt_dict.get("dateTime", "")
    tz_name = dt_dict.get("timeZone", "UTC")

    # Graph often returns "UTC" as timeZone; handle that directly
    if tz_name == "UTC":
        # Strip fractional seconds beyond microseconds if present
        if "." in raw:
            base, frac = raw.split(".")
            frac = frac[:6]
            raw = f"{base}.{frac}"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # For non-UTC timezones, attempt isoformat parse and assume UTC if naive
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _extract_thread_id(join_url: str) -> str:
    """Extract the Teams chat thread ID from a meeting join URL.

    Teams join URLs contain the thread ID encoded in the URL path, e.g.::

        https://teams.microsoft.com/l/meetup-join/19%3ameeting_<id>%40thread.v2/...

    Args:
        join_url: The full Teams meeting join URL.

    Returns:
        The decoded thread ID, or the raw URL if extraction fails.
    """
    from urllib.parse import unquote

    match = re.search(r"meetup-join/([^/]+)", join_url)
    if match:
        return unquote(match.group(1))
    return join_url


async def _execute_bot_join(meeting_id: str) -> None:
    """APScheduler job — tells the C# Media Bot to join a meeting.

    This is a standalone async function (not a method) so APScheduler can
    serialize / invoke it.  It creates a fresh DB session to avoid stale
    session issues from the long-lived scheduler.

    Uses the shared BotCommander from app.state (set up in lifespan) to
    reuse HTTP connections. Falls back to creating a new one if unavailable.
    """
    from app.dependencies import async_session_factory

    logger.info("Executing scheduled bot join", extra={"meeting_id": meeting_id})

    async with async_session_factory() as db:
        result = await db.execute(
            select(Meeting).where(
                Meeting.id == meeting_id,
                Meeting.status == "scheduled",
            )
        )
        meeting = result.scalar_one_or_none()
        if meeting is None:
            logger.warning(
                "Meeting not found or not in scheduled state — skipping join",
                extra={"meeting_id": meeting_id},
            )
            return

        # Use shared BotCommander from app.state, fall back to ephemeral
        bot: BotCommander | None = None
        owns_bot = False
        try:
            from app.main import app

            bot = getattr(app.state, "bot_commander", None)
        except Exception:
            pass

        if bot is None:
            from app.config import Settings
            from app.services.bot_commander import BotCommander

            bot = BotCommander(settings=Settings())
            owns_bot = True

        try:
            call_id = await bot.join_meeting(
                meeting_id=str(meeting.id),
                join_url=meeting.join_url,
            )
            meeting.status = "joining"
            meeting.acs_call_connection_id = call_id  # reuse column for bot call_id
            await db.commit()
            logger.info(
                "Bot join requested for meeting %s, call_id=%s",
                meeting_id,
                call_id,
            )
        except Exception:
            logger.exception(
                "Failed to request bot join for meeting %s",
                meeting_id,
            )
            meeting.status = "failed"
            await db.commit()
        finally:
            if owns_bot and bot is not None:
                await bot.close()
