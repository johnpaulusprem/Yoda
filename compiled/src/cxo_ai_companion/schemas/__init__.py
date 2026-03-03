"""CXO AI Companion -- Pydantic v2 schemas package."""

from __future__ import annotations

# Meeting
from cxo_ai_companion.schemas.meeting import (
    MeetingCreateRequest,
    MeetingDetailResponse,
    MeetingListResponse,
    MeetingResponse,
    MeetingUpdateRequest,
    MeetingWithTagsResponse,
    ParticipantResponse,
)

# Transcript
from cxo_ai_companion.schemas.transcript import (
    TranscriptResponse,
    TranscriptSegmentResponse,
)

# Summary
from cxo_ai_companion.schemas.summary import (
    DecisionResponse,
    KeyTopicResponse,
    SummaryResponse,
    SummaryShareRequest,
    SummaryShareResponse,
    SummaryUpdateRequest,
)

# Action items
from cxo_ai_companion.schemas.action_item import (
    ActionItemCreateRequest,
    ActionItemListResponse,
    ActionItemResponse,
    ActionItemUpdateRequest,
)

# Webhooks
from cxo_ai_companion.schemas.webhook import (
    GraphNotification,
    GraphValidationResponse,
    GraphWebhookPayload,
)

# ACS
from cxo_ai_companion.schemas.acs import (
    ACSCallbackEvent,
    ACSCallConnectedEvent,
    ACSCallDisconnectedEvent,
    ACSTranscriptionEvent,
)

# Dashboard (CXO wireframe)
from cxo_ai_companion.schemas.dashboard import (
    ActivityFeedResponse,
    AttentionItemResponse,
    DashboardStatsResponse,
    QuickActionResponse,
)

# Chat (Ask AI / RAG)
from cxo_ai_companion.schemas.chat import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionResponse,
    ChatSessionListResponse,
    ChatSourceCitation,
)

# Document
from cxo_ai_companion.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
)

# Insight
from cxo_ai_companion.schemas.insight import (
    InsightListResponse,
    InsightResponse,
    WeeklyDigestResponse,
)

# Notification
from cxo_ai_companion.schemas.notification import (
    NotificationListResponse,
    NotificationResponse,
)

# Pre-meeting brief
from cxo_ai_companion.schemas.pre_meeting_brief import (
    AttendeeContextResponse,
    EmailThreadResponse,
    PastDecisionResponse,
    PreMeetingBriefResponse,
    RelatedDocumentResponse,
)

# Search
from cxo_ai_companion.schemas.search import (
    SearchResponse,
    SearchResultItem,
)

# Project
from cxo_ai_companion.schemas.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

__all__ = [
    # Meeting
    "MeetingCreateRequest",
    "MeetingDetailResponse",
    "MeetingListResponse",
    "MeetingResponse",
    "MeetingUpdateRequest",
    "MeetingWithTagsResponse",
    "ParticipantResponse",
    # Transcript
    "TranscriptResponse",
    "TranscriptSegmentResponse",
    # Summary
    "DecisionResponse",
    "KeyTopicResponse",
    "SummaryResponse",
    "SummaryShareRequest",
    "SummaryShareResponse",
    "SummaryUpdateRequest",
    # Action items
    "ActionItemCreateRequest",
    "ActionItemListResponse",
    "ActionItemResponse",
    "ActionItemUpdateRequest",
    # Webhooks
    "GraphNotification",
    "GraphValidationResponse",
    "GraphWebhookPayload",
    # ACS
    "ACSCallbackEvent",
    "ACSCallConnectedEvent",
    "ACSCallDisconnectedEvent",
    "ACSTranscriptionEvent",
    # Dashboard
    "ActivityFeedResponse",
    "AttentionItemResponse",
    "DashboardStatsResponse",
    "QuickActionResponse",
    # Chat
    "ChatMessageRequest",
    "ChatMessageResponse",
    "ChatSessionResponse",
    "ChatSessionListResponse",
    "ChatSourceCitation",
    # Document
    "DocumentListResponse",
    "DocumentResponse",
    # Insight
    "InsightListResponse",
    "InsightResponse",
    "WeeklyDigestResponse",
    # Notification
    "NotificationListResponse",
    "NotificationResponse",
    # Pre-meeting brief
    "AttendeeContextResponse",
    "EmailThreadResponse",
    "PastDecisionResponse",
    "PreMeetingBriefResponse",
    "RelatedDocumentResponse",
    # Search
    "SearchResponse",
    "SearchResultItem",
    # Project
    "ProjectCreateRequest",
    "ProjectListResponse",
    "ProjectResponse",
    "ProjectUpdateRequest",
]
