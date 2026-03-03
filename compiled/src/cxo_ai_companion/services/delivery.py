"""Delivery service -- enterprise edition.

Posts Adaptive Cards to Teams via Microsoft Graph API. Handles delivery of
meeting summaries, nudge reminders, escalations, and weekly digest cards.

Ported from ``teams-meeting-assistant/app/services/delivery.py`` with:
- CXO exceptions (DeliveryError)
- Tracing spans via observability
- Metrics (delivery_sent, nudges_sent, escalations_sent)
- Kept Adaptive Card posting, nudge cards, weekly digest cards
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cxo_ai_companion.exceptions import DeliveryError
from cxo_ai_companion.models.action_item import ActionItem
from cxo_ai_companion.models.meeting import Meeting
from cxo_ai_companion.models.summary import MeetingSummary
from cxo_ai_companion.observability import get_logger, metrics, trace_span
from cxo_ai_companion.security.context import SecurityContext, create_system_context

logger = get_logger("services.delivery")

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


# ======================================================================
# Template helpers (module-level)
# ======================================================================


def _load_template(template_name: str) -> str:
    """Load an Adaptive Card JSON template from the templates directory."""
    template_path = TEMPLATES_DIR / template_name
    try:
        with open(template_path) as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("Template not found: %s -- using fallback", template_name)
        return "{}"


def _format_duration(start: datetime, end: datetime) -> str:
    """Format a duration between two datetimes as a human-readable string."""
    delta = end - start
    total_minutes = int(delta.total_seconds() / 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_deadline(deadline: datetime | None) -> str:
    """Format a deadline datetime to a readable string."""
    if deadline is None:
        return "No deadline"
    return deadline.strftime("%b %d, %Y")


def _format_date(dt: datetime) -> str:
    """Format a datetime to a readable date/time string."""
    return dt.strftime("%b %d, %Y at %I:%M %p")


def _priority_label(priority: str) -> str:
    """Format priority with visual indicators for Adaptive Card display."""
    labels = {
        "high": "HIGH",
        "medium": "Medium",
        "low": "Low",
    }
    return labels.get(priority.lower(), priority)


def _build_action_items_rows(action_items: list[ActionItem]) -> str:
    """Build a formatted text block for action items."""
    if not action_items:
        return "No action items recorded."

    rows: list[str] = []
    for i, item in enumerate(action_items, start=1):
        deadline_str = _format_deadline(item.deadline)
        priority_str = _priority_label(item.priority)
        rows.append(
            f"{i}. **{item.description}** | "
            f"{item.assigned_to_name} | "
            f"{deadline_str} | "
            f"{priority_str}"
        )
    return "\n\n".join(rows)


def _build_decisions_list(decisions: list[dict[str, Any]]) -> str:
    """Build a formatted decisions list from the summary decisions JSON."""
    if not decisions:
        return "No decisions recorded."

    lines: list[str] = []
    for i, decision in enumerate(decisions, start=1):
        if isinstance(decision, dict):
            text = decision.get("text") or decision.get("decision") or str(decision)
        else:
            text = str(decision)
        lines.append(f"{i}. {text}")
    return "\n\n".join(lines)


def _build_key_topics(topics: list[dict[str, Any]]) -> str:
    """Build a formatted key topics list."""
    if not topics:
        return "No key topics identified."

    lines: list[str] = []
    for i, topic in enumerate(topics, start=1):
        if isinstance(topic, dict):
            text = topic.get("topic") or topic.get("text") or str(topic)
        else:
            text = str(topic)
        lines.append(f"{i}. {text}")
    return "\n\n".join(lines)


def _build_unresolved_questions(questions: list[str]) -> str:
    """Build a formatted list of unresolved questions."""
    if not questions:
        return "No unresolved questions."

    lines: list[str] = []
    for i, question in enumerate(questions, start=1):
        lines.append(f"{i}. {question}")
    return "\n\n".join(lines)


def _populate_template(template_str: str, replacements: dict[str, str]) -> dict[str, Any]:
    """Replace ${variable} placeholders in the template string and parse as JSON.

    Performs string replacement on the raw template text, then parses the
    result into a dict suitable for posting as an Adaptive Card attachment.
    """
    populated = template_str
    for key, value in replacements.items():
        safe_value = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        populated = populated.replace(f"${{{key}}}", safe_value)

    try:
        return json.loads(populated)
    except json.JSONDecodeError:
        logger.error("Failed to parse populated template as JSON")
        return {}


# ======================================================================
# DeliveryService
# ======================================================================


class DeliveryService:
    """Posts Adaptive Cards to Teams via Microsoft Graph API.

    Handles delivery of meeting summaries, nudge reminders, and escalations
    by loading JSON templates, populating them with data, and sending via
    the GraphClient.

    Args:
        graph_client: GraphClient instance for posting messages to Teams.
        settings: Application settings (BASE_URL for transcript links).
    """

    def __init__(self, graph_client: Any, settings: Any) -> None:
        self.graph = graph_client
        self.settings = settings

    async def deliver_summary(
        self,
        meeting: Meeting,
        summary: MeetingSummary,
        action_items: list[ActionItem],
        ctx: SecurityContext | None = None,
    ) -> None:
        """Post the meeting summary as an Adaptive Card to the meeting's Teams chat.

        Steps:
        1. Load the summary_card.json template.
        2. Populate it with meeting data, summary, action items, and decisions.
        3. Post to the meeting chat via Graph API.
        4. Update summary.delivered and summary.delivered_at.

        Raises:
            DeliveryError: When the card cannot be posted to Teams.
        """
        ctx = ctx or create_system_context()

        async with trace_span(
            "delivery.deliver_summary",
            attributes={"meeting_id": str(meeting.id)},
        ):
            try:
                template_str = _load_template("summary_card.json")

                start = meeting.actual_start or meeting.scheduled_start
                end = meeting.actual_end or meeting.scheduled_end
                duration = _format_duration(start, end)

                action_items_rows = _build_action_items_rows(action_items)
                decisions_list = _build_decisions_list(summary.decisions or [])
                key_topics = _build_key_topics(summary.key_topics or [])
                unresolved_questions = _build_unresolved_questions(
                    summary.unresolved_questions or []
                )

                transcript_url = (
                    f"{self.settings.BASE_URL}/api/meetings/{meeting.id}/transcript"
                )

                replacements = {
                    "meeting_title": meeting.subject,
                    "meeting_date": _format_date(meeting.scheduled_start),
                    "duration": duration,
                    "participant_count": str(meeting.participant_count),
                    "summary_text": summary.summary_text,
                    "key_topics": key_topics,
                    "action_item_count": str(len(action_items)),
                    "action_items_rows": action_items_rows,
                    "decisions_count": str(len(summary.decisions or [])),
                    "decisions_list": decisions_list,
                    "unresolved_questions": unresolved_questions,
                    "model_used": summary.model_used,
                    "transcript_url": transcript_url,
                }

                card = _populate_template(template_str, replacements)

                logger.info(
                    "Delivering summary card for meeting %s to thread %s",
                    meeting.id,
                    meeting.thread_id,
                )

                if meeting.thread_id:
                    await self.graph.send_chat_message(
                        meeting.thread_id, card, ctx=ctx,
                    )

                # Mark summary as delivered
                summary.delivered = True
                summary.delivered_at = datetime.now(timezone.utc)

                metrics["delivery_sent"].add(1)

                logger.info(
                    "Summary delivered for meeting %s at %s",
                    meeting.id,
                    summary.delivered_at.isoformat(),
                )

            except Exception as exc:
                raise DeliveryError(
                    message=f"Failed to deliver summary for meeting {meeting.id}",
                    channel="chat",
                    recipient=meeting.thread_id,
                    cause=exc,
                ) from exc

    async def send_nudge(
        self,
        action_item: ActionItem,
        ctx: SecurityContext | None = None,
    ) -> None:
        """Send a 1:1 nudge reminder to the action item owner.

        Loads the nudge_card.json template, populates it with the action item
        details, and sends via proactive message. Updates nudge tracking fields.

        Raises:
            DeliveryError: When the nudge cannot be sent.
        """
        ctx = ctx or create_system_context()

        async with trace_span(
            "delivery.send_nudge",
            attributes={"action_item_id": str(action_item.id)},
        ):
            try:
                template_str = _load_template("nudge_card.json")

                now = datetime.now(timezone.utc)
                if action_item.deadline is not None:
                    time_until = action_item.deadline - now
                    hours_until = time_until.total_seconds() / 3600

                    if hours_until < 0:
                        overdue_hours = abs(hours_until)
                        if overdue_hours >= 24:
                            days_overdue = int(overdue_hours / 24)
                            deadline_message = f"OVERDUE by {days_overdue} day(s)!"
                        else:
                            deadline_message = f"OVERDUE by {int(overdue_hours)} hour(s)!"
                        deadline_color = "Attention"
                    elif hours_until <= 24:
                        deadline_message = f"Due in {int(hours_until)} hour(s) - approaching deadline!"
                        deadline_color = "Warning"
                    else:
                        days_until = int(hours_until / 24)
                        deadline_message = f"Due in {days_until} day(s)"
                        deadline_color = "Default"
                else:
                    deadline_message = "No deadline set"
                    deadline_color = "Default"

                meeting_subject = "Unknown Meeting"
                meeting_date = "Unknown"
                if action_item.meeting is not None:
                    meeting_subject = action_item.meeting.subject
                    meeting_date = _format_date(action_item.meeting.scheduled_start)

                replacements = {
                    "description": action_item.description,
                    "meeting_subject": meeting_subject,
                    "meeting_date": meeting_date,
                    "deadline": _format_deadline(action_item.deadline),
                    "priority": _priority_label(action_item.priority),
                    "status": action_item.status,
                    "nudge_number": str(action_item.nudge_count + 1),
                    "deadline_message": deadline_message,
                    "deadline_color": deadline_color,
                    "item_id": str(action_item.id),
                }

                card = _populate_template(template_str, replacements)

                recipient = action_item.assigned_to_user_id
                if not recipient:
                    logger.warning(
                        "Action item %s has no assigned user ID, cannot send nudge to %s",
                        action_item.id,
                        action_item.assigned_to_name,
                    )
                    return

                logger.info(
                    "Sending nudge #%d for action item %s to user %s",
                    action_item.nudge_count + 1,
                    action_item.id,
                    recipient,
                )
                await self.graph.send_proactive_message(recipient, card, ctx=ctx)

                # Update nudge tracking
                action_item.nudge_count += 1
                action_item.last_nudge_at = datetime.now(timezone.utc)

                metrics["nudges_sent"].add(1)

                logger.info(
                    "Nudge sent for action item %s, total nudges: %d",
                    action_item.id,
                    action_item.nudge_count,
                )

            except DeliveryError:
                raise
            except Exception as exc:
                raise DeliveryError(
                    message=f"Failed to send nudge for action item {action_item.id}",
                    channel="chat",
                    recipient=action_item.assigned_to_user_id,
                    cause=exc,
                ) from exc

    async def send_escalation(
        self,
        action_item: ActionItem,
        meeting: Meeting,
        ctx: SecurityContext | None = None,
    ) -> None:
        """Notify the meeting organizer after too many missed nudges.

        Raises:
            DeliveryError: When the escalation cannot be sent.
        """
        ctx = ctx or create_system_context()

        async with trace_span(
            "delivery.send_escalation",
            attributes={
                "action_item_id": str(action_item.id),
                "meeting_id": str(meeting.id),
            },
        ):
            try:
                template_str = _load_template("nudge_card.json")

                deadline_message = (
                    f"ESCALATION: This action item has been nudged "
                    f"{action_item.nudge_count} time(s) without resolution. "
                    f"Assigned to {action_item.assigned_to_name}."
                )

                replacements = {
                    "description": action_item.description,
                    "meeting_subject": meeting.subject,
                    "meeting_date": _format_date(meeting.scheduled_start),
                    "deadline": _format_deadline(action_item.deadline),
                    "priority": _priority_label(action_item.priority),
                    "status": action_item.status,
                    "nudge_number": str(action_item.nudge_count),
                    "deadline_message": deadline_message,
                    "deadline_color": "Attention",
                    "item_id": str(action_item.id),
                }

                card = _populate_template(template_str, replacements)

                organizer_id = meeting.organizer_id
                if not organizer_id:
                    logger.warning(
                        "Meeting %s has no organizer_id, cannot send escalation",
                        meeting.id,
                    )
                    return

                logger.info(
                    "Sending escalation for action item %s to organizer %s "
                    "(meeting %s, nudge count: %d)",
                    action_item.id,
                    organizer_id,
                    meeting.id,
                    action_item.nudge_count,
                )
                await self.graph.send_proactive_message(organizer_id, card, ctx=ctx)

                # Update nudge tracking to record that escalation was sent
                action_item.last_nudge_at = datetime.now(timezone.utc)

                metrics["escalations_sent"].add(1)

                logger.info(
                    "Escalation sent for action item %s to organizer %s",
                    action_item.id,
                    organizer_id,
                )

            except DeliveryError:
                raise
            except Exception as exc:
                raise DeliveryError(
                    message=f"Failed to send escalation for action item {action_item.id}",
                    channel="chat",
                    recipient=meeting.organizer_id,
                    cause=exc,
                ) from exc
