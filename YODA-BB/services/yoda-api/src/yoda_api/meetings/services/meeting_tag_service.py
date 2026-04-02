"""Meeting tag computation service.

Computes UI display tags for meetings based on meeting metadata,
action items, summary content, and pre-meeting brief availability.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

# Patterns that indicate a recurring meeting subject
_RECURRING_PATTERNS = re.compile(
    r"(daily|weekly|biweekly|bi-weekly|monthly|standup|stand-up|sync|1:1|one-on-one|retro|retrospective|sprint|scrum)",
    re.IGNORECASE,
)


def compute_tags(
    meeting: Any,
    *,
    action_items: Sequence[Any] | None = None,
    has_brief: bool = False,
    summary: Any | None = None,
) -> list[str]:
    """Compute display tags for a single meeting.

    Args:
        meeting: A Meeting ORM instance or object with ``status``,
            ``subject``, ``organizer_email``, and optionally ``participants``.
        action_items: Action items associated with the meeting.  May be
            ORM instances or dicts with a ``priority`` key.
        has_brief: Whether a pre-meeting brief exists for the meeting.
        summary: The meeting summary (ORM instance or object with
            ``unresolved_questions``), or ``None``.

    Returns:
        Sorted list of tag strings for UI display.
    """
    tags: list[str] = []
    items = action_items or []

    # --- Brief Ready ---
    if has_brief:
        tags.append("Brief Ready")

    # --- Has Actions / High Priority ---
    if items:
        tags.append("Has Actions")
        has_high = any(
            (getattr(ai, "priority", None) or (ai.get("priority") if isinstance(ai, dict) else None)) == "high"
            for ai in items
        )
        if has_high:
            tags.append("High Priority")

    # --- Recurring ---
    subject = getattr(meeting, "subject", "") or ""
    if _RECURRING_PATTERNS.search(subject):
        tags.append("Recurring")

    # --- External ---
    organizer_email = getattr(meeting, "organizer_email", "") or ""
    organizer_domain = _domain(organizer_email)
    participants = getattr(meeting, "participants", None) or []
    if organizer_domain and participants:
        for p in participants:
            p_email = getattr(p, "email", None) or ""
            p_domain = _domain(p_email)
            if p_domain and p_domain != organizer_domain:
                tags.append("External")
                break

    # --- Decision Needed ---
    if summary is not None:
        unresolved = getattr(summary, "unresolved_questions", None) or []
        if unresolved:
            tags.append("Decision Needed")

    # --- Status-based tags ---
    status = getattr(meeting, "status", "")
    if status == "in_progress":
        tags.append("In Progress")
    elif status == "completed" and summary is not None:
        tags.append("Completed")

    return sorted(tags)


def _domain(email: str) -> str:
    """Extract the domain part from an email address."""
    if "@" in email:
        return email.rsplit("@", 1)[1].lower()
    return ""
