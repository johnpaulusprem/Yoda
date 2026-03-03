"""Service layer re-exports.

All service classes are re-exported here for convenient access:

    from cxo_ai_companion.services import GraphClient, ChatService, ...

Services 1-9 are enterprise ports of the original meeting assistant.
Services 10+ are CXO-specific services.
"""
from __future__ import annotations

# --- Ported enterprise services (1-9) ---
from cxo_ai_companion.services.graph_client import GraphClient
from cxo_ai_companion.services.calendar_watcher import CalendarWatcher
from cxo_ai_companion.services.acs_call_service import ACSCallService
from cxo_ai_companion.services.transcription import TranscriptionHandler
from cxo_ai_companion.services.ai_processor import AIProcessor
from cxo_ai_companion.services.owner_resolver import OwnerResolver
from cxo_ai_companion.services.delivery import DeliveryService
from cxo_ai_companion.services.nudge_scheduler import NudgeScheduler

# --- New CXO-specific services (10+) ---
from cxo_ai_companion.services.dashboard_service import DashboardService
from cxo_ai_companion.services.pre_meeting_service import PreMeetingService
from cxo_ai_companion.services.chat_service import ChatService
from cxo_ai_companion.services.document_service import DocumentService
from cxo_ai_companion.services.insight_service import InsightService
from cxo_ai_companion.services.weekly_digest_service import WeeklyDigestService
from cxo_ai_companion.services.notification_service import NotificationService
from cxo_ai_companion.services.conflict_detection_service import ConflictDetectionService

__all__ = [
    # Ported enterprise services
    "GraphClient",
    "CalendarWatcher",
    "ACSCallService",
    "TranscriptionHandler",
    "AIProcessor",
    "OwnerResolver",
    "DeliveryService",
    "NudgeScheduler",
    # New CXO-specific services
    "DashboardService",
    "PreMeetingService",
    "ChatService",
    "DocumentService",
    "InsightService",
    "WeeklyDigestService",
    "NotificationService",
    "ConflictDetectionService",
]
