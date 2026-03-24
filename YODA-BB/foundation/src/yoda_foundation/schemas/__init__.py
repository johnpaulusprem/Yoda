"""CXO AI Companion -- Pydantic v2 schemas package."""

from __future__ import annotations

# Meeting
from yoda_foundation.schemas.meeting import (
    CreateMeetingRequest,
    MeetingCreateRequest,
    MeetingDetailResponse,
    MeetingListResponse,
    MeetingResponse,
    MeetingUpdateRequest,
    MeetingWithTagsResponse,
    ParticipantResponse,
    _extract_thread_id_from_join_url,
)

# Transcript
from yoda_foundation.schemas.transcript import (
    TranscriptResponse,
    TranscriptSegmentResponse,
)

# Summary
from yoda_foundation.schemas.summary import (
    DecisionResponse,
    KeyTopicResponse,
    SummaryResponse,
    SummaryShareRequest,
    SummaryShareResponse,
    SummaryUpdateRequest,
)

# Action items
from yoda_foundation.schemas.action_item import (
    ActionItemCreateRequest,
    ActionItemListResponse,
    ActionItemResponse,
    ActionItemUpdate,
    ActionItemUpdateRequest,
)

# Webhooks
from yoda_foundation.schemas.webhook import (
    GraphChangeNotification,
    GraphNotification,
    GraphValidationResponse,
    GraphWebhookPayload,
)

# ACS
from yoda_foundation.schemas.acs import (
    ACSCallbackEvent,
    ACSCallConnectedEvent,
    ACSCallDisconnectedEvent,
    ACSTranscriptionEvent,
)

# Dashboard (CXO wireframe)
from yoda_foundation.schemas.dashboard import (
    ActivityFeedResponse,
    AttentionItemResponse,
    DashboardStatsResponse,
    QuickActionResponse,
)

# Chat (Ask AI / RAG)
from yoda_foundation.schemas.chat import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionResponse,
    ChatSessionListResponse,
    ChatSourceCitation,
)

# Document
from yoda_foundation.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
)

# Insight
from yoda_foundation.schemas.insight import (
    InsightListResponse,
    InsightResponse,
    WeeklyDigestResponse,
)

# Notification
from yoda_foundation.schemas.notification import (
    NotificationListResponse,
    NotificationResponse,
)

# Pre-meeting brief
from yoda_foundation.schemas.pre_meeting_brief import (
    AttendeeContextResponse,
    EmailThreadResponse,
    PastDecisionResponse,
    PreMeetingBriefResponse,
    RelatedDocumentResponse,
)

# Search
from yoda_foundation.schemas.search import (
    SearchResponse,
    SearchResultItem,
)

# Project
from yoda_foundation.schemas.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

__all__ = [
    # Meeting
    "CreateMeetingRequest",
    "MeetingCreateRequest",
    "MeetingDetailResponse",
    "MeetingListResponse",
    "MeetingResponse",
    "MeetingUpdateRequest",
    "MeetingWithTagsResponse",
    "ParticipantResponse",
    "_extract_thread_id_from_join_url",
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
    "ActionItemUpdate",
    "ActionItemUpdateRequest",
    # Webhooks
    "GraphChangeNotification",
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
