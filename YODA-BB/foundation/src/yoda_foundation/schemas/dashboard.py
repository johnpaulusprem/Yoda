"""Pydantic v2 schemas for the CXO dashboard wireframe features."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DashboardStatsResponse(BaseModel):
    """High-level statistics displayed at the top of the CXO dashboard.

    Computed on the fly from meeting and action-item data for the
    authenticated user.

    Attributes:
        meetings_today: Number of meetings scheduled for today.
        pending_actions: Action items in pending or in_progress state.
        overdue_actions: Action items past their deadline.
        completion_rate: Percentage of completed action items (0.0--100.0).
    """

    meetings_today: int = Field(description="Number of meetings scheduled for today")
    pending_actions: int = Field(description="Action items in pending/in_progress state")
    overdue_actions: int = Field(description="Action items past their deadline")
    completion_rate: float = Field(
        description="Percentage of completed action items (0.0-100.0)"
    )


class AttentionItemResponse(BaseModel):
    """A single item requiring the user's attention on the dashboard.

    Covers overdue tasks, scheduling conflicts, follow-ups, and escalations.
    Serialized from the AttentionItem ORM model via ``from_attributes=True``.

    Attributes:
        id: Unique attention item identifier (UUID).
        item_type: Category (overdue_action, conflict, follow_up, escalation).
        title: Short headline for the attention item.
        description: Detailed explanation of why attention is needed.
        severity: Urgency level (info, warning, critical).
        related_meeting_id: Associated meeting, if applicable.
        related_meeting_subject: Subject of the related meeting.
        action_url: Deep link to resolve or act on this item.
        created_at: Timestamp when the attention item was created.
    """

    id: uuid.UUID
    item_type: str = Field(
        description="Type of attention item: overdue_action, conflict, follow_up, escalation"
    )
    title: str
    description: str
    severity: str = Field(description="info, warning, or critical")
    related_meeting_id: uuid.UUID | None = None
    related_meeting_subject: str | None = None
    action_url: str | None = Field(
        default=None, description="Deep link to resolve this item"
    )
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActivityFeedResponse(BaseModel):
    """A single entry in the user's activity feed / timeline.

    Represents a chronological event such as a completed meeting, delivered
    summary, or action item update. Serialized via ``from_attributes=True``.

    Attributes:
        id: Unique activity entry identifier (UUID).
        activity_type: Event kind (meeting_completed, summary_delivered, action_created,
            action_completed, nudge_sent, digest_delivered).
        title: Short headline for the activity.
        description: Detailed description of the activity event.
        meeting_id: Associated meeting, if applicable.
        meeting_subject: Subject of the related meeting.
        timestamp: When the activity occurred.
        read: Whether the user has acknowledged this entry.
    """

    id: uuid.UUID
    activity_type: str = Field(
        description="Type of activity: meeting_completed, summary_delivered, action_created, action_completed, nudge_sent, digest_delivered"
    )
    title: str
    description: str
    meeting_id: uuid.UUID | None = None
    meeting_subject: str | None = None
    timestamp: datetime
    read: bool = False

    model_config = ConfigDict(from_attributes=True)


class QuickActionResponse(BaseModel):
    """A quick-action button available on the CXO dashboard.

    Quick actions provide one-click shortcuts for common tasks such as
    viewing pending items or triggering a digest.

    Attributes:
        action_id: Unique identifier for this quick action.
        label: Button label text.
        description: Tooltip or subtitle describing the action.
        icon: Icon name or URL for the action button.
        action_type: Interaction type (navigate, api_call, modal).
        action_target: URL, API endpoint, or modal ID to invoke.
        enabled: Whether the action is currently available.
    """

    action_id: str = Field(description="Unique identifier for this quick action")
    label: str
    description: str
    icon: str | None = Field(
        default=None, description="Icon name or URL for the action button"
    )
    action_type: str = Field(
        description="Type of action: navigate, api_call, modal"
    )
    action_target: str = Field(
        description="URL, API endpoint, or modal ID to invoke"
    )
    enabled: bool = True
