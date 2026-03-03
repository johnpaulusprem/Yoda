"""CXO AI Companion -- ORM models package."""

from __future__ import annotations

from cxo_ai_companion.models.base import Base, TimestampMixin, UUIDMixin
from cxo_ai_companion.models.meeting import Meeting, MeetingParticipant
from cxo_ai_companion.models.transcript import TranscriptSegment
from cxo_ai_companion.models.summary import MeetingSummary
from cxo_ai_companion.models.action_item import ActionItem
from cxo_ai_companion.models.subscription import GraphSubscription, UserPreference
from cxo_ai_companion.models.document import Document, DocumentChunk
from cxo_ai_companion.models.insight import MeetingInsight, WeeklyDigest
from cxo_ai_companion.models.chat import ChatSession, ChatMessage
from cxo_ai_companion.models.notification import Notification
from cxo_ai_companion.models.project import Project, project_meetings_table

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDMixin",
    "Meeting",
    "MeetingParticipant",
    "TranscriptSegment",
    "MeetingSummary",
    "ActionItem",
    "GraphSubscription",
    "UserPreference",
    "Document",
    "DocumentChunk",
    "MeetingInsight",
    "WeeklyDigest",
    "ChatSession",
    "ChatMessage",
    "Notification",
    "Project",
    "project_meetings_table",
]
