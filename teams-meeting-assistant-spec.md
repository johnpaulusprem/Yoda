# Teams Meeting Assistant Bot — Backend Development Specification

## For Claude Code: Build this project following every instruction below exactly.

---

## 1. Project Overview

Build the **complete backend** for a Teams Meeting Assistant Bot that:

1. Watches user calendars for upcoming Teams meetings (via Microsoft Graph API)
2. Autonomously joins each meeting using **Azure Communication Services (ACS) Call Automation** — capturing audio independently, regardless of whether Teams transcription is enabled
3. Receives real-time transcription via ACS WebSocket streaming
4. After the meeting ends, sends the transcript to **Azure AI Foundry** (GPT-4o-mini or GPT-4o) to generate summaries, action items, decisions, and key topics
5. Delivers the summary as an **Adaptive Card** to the Teams meeting chat via Graph API
6. Runs a **nudge scheduler** that reminds action item owners about approaching or overdue deadlines

**The UI already exists.** You are building only the backend services and API layer.

---

## 2. Technology Stack

| Layer | Technology | Reason |
|-------|-----------|--------|
| Language | **Python 3.11+** | ACS has strong Python SDK support |
| Web Framework | **FastAPI** | Async-native, lightweight, OpenAPI docs built-in |
| Database | **PostgreSQL** (Azure Flexible Server) | Low cost, pgvector for future RAG |
| ORM | **SQLAlchemy 2.0** (async with asyncpg) | Industry standard, async support |
| Migrations | **Alembic** | SQLAlchemy's migration companion |
| Task Queue | **APScheduler** or **Celery with Redis** | For scheduled nudges and delayed meeting joins |
| WebSocket Server | **FastAPI WebSocket** endpoint | Receives ACS audio/transcription streams |
| Hosting | **Azure Container Apps** | Cheapest serverless container option |
| Container | **Docker** | Standard containerization |

---

## 3. Project Structure

Create this exact directory structure:

```
teams-meeting-assistant/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app entry point
│   ├── config.py                  # Settings via pydantic-settings
│   ├── dependencies.py            # Dependency injection (DB session, clients)
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py                # SQLAlchemy Base, common mixins
│   │   ├── meeting.py             # Meeting, MeetingParticipant models
│   │   ├── transcript.py          # TranscriptSegment model
│   │   ├── summary.py             # MeetingSummary model
│   │   ├── action_item.py         # ActionItem model
│   │   └── subscription.py        # GraphSubscription, UserPreference models
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── meeting.py             # Pydantic request/response schemas
│   │   ├── transcript.py
│   │   ├── summary.py
│   │   ├── action_item.py
│   │   ├── webhook.py             # Graph webhook payload schemas
│   │   └── acs.py                 # ACS callback/event schemas
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── graph_client.py        # Microsoft Graph API wrapper
│   │   ├── calendar_watcher.py    # Calendar subscription + webhook handler
│   │   ├── acs_call_service.py    # ACS Call Automation: join, audio stream, transcription
│   │   ├── transcription.py       # WebSocket handler for ACS transcription stream
│   │   ├── ai_processor.py        # Azure AI Foundry: summary + action item extraction
│   │   ├── delivery.py            # Post Adaptive Cards to Teams chat
│   │   ├── nudge_scheduler.py     # Scheduled nudge engine
│   │   └── owner_resolver.py      # Fuzzy match names to Graph users
│   │
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── webhooks.py            # POST /webhooks/graph — calendar change notifications
│   │   ├── acs_callbacks.py       # POST /callbacks/acs — ACS call events
│   │   ├── meetings.py            # GET/POST meeting endpoints for the UI
│   │   ├── action_items.py        # CRUD for action items (UI consumption)
│   │   └── health.py              # GET /health
│   │
│   ├── templates/
│   │   ├── summary_card.json      # Adaptive Card template: post-meeting summary
│   │   ├── nudge_card.json        # Adaptive Card template: action item nudge
│   │   └── weekly_digest_card.json
│   │
│   └── utils/
│       ├── __init__.py
│       ├── auth.py                # MSAL token acquisition for Graph + ACS
│       ├── logging_config.py      # Structured logging setup
│       └── retry.py               # Tenacity-based retry decorator
│
├── alembic/
│   ├── env.py
│   ├── versions/                  # Migration files
│   └── alembic.ini
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Fixtures: test DB, mock clients
│   ├── test_calendar_watcher.py
│   ├── test_acs_call_service.py
│   ├── test_ai_processor.py
│   ├── test_delivery.py
│   ├── test_nudge_scheduler.py
│   └── test_owner_resolver.py
│
├── deployment/
│   ├── Dockerfile
│   ├── docker-compose.yml         # Local dev: app + postgres + redis
│   ├── bicep/                     # Azure Container Apps IaC
│   │   ├── main.bicep
│   │   └── modules/
│   └── .env.template
│
├── scripts/
│   ├── setup_acs_federation.ps1   # PowerShell: enable Teams-ACS interop
│   ├── grant_graph_permissions.sh # CLI script to grant admin consent
│   └── seed_db.py                 # Seed test data
│
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## 4. Configuration (`app/config.py`)

Use `pydantic-settings` to load all config from environment variables. Every secret must come from env vars, never hardcoded.

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App
    APP_NAME: str = "teams-meeting-assistant"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    BASE_URL: str  # Public URL, e.g. https://your-app.azurecontainerapps.io

    # Database
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host:5432/dbname

    # Microsoft Entra ID (Azure AD)
    AZURE_TENANT_ID: str
    AZURE_CLIENT_ID: str
    AZURE_CLIENT_SECRET: str

    # Azure Communication Services
    ACS_CONNECTION_STRING: str
    ACS_ENDPOINT: str  # https://<resource>.communication.azure.com

    # Azure AI Foundry
    AI_FOUNDRY_ENDPOINT: str  # https://<resource>.openai.azure.com/
    AI_FOUNDRY_API_KEY: str
    AI_FOUNDRY_DEPLOYMENT_NAME: str = "gpt-4o-mini"  # default to cheap model
    AI_FOUNDRY_DEPLOYMENT_NAME_COMPLEX: str = "gpt-4o"  # for long/complex meetings

    # Meeting Bot Behavior
    BOT_DISPLAY_NAME: str = "Meeting Assistant"
    BOT_JOIN_BEFORE_MINUTES: int = 1
    NUDGE_CHECK_INTERVAL_MINUTES: int = 30
    NUDGE_ESCALATION_THRESHOLD: int = 2  # escalate after N missed nudges
    LONG_MEETING_THRESHOLD_MINUTES: int = 120  # chunk transcripts above this

    # Redis (for task queue, optional)
    REDIS_URL: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"
```

---

## 5. Database Models (`app/models/`)

Use SQLAlchemy 2.0 async style. All models must have `id` (UUID primary key), `created_at`, `updated_at`.

### `base.py`
```python
import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

### `meeting.py`
```python
class Meeting(Base, TimestampMixin):
    __tablename__ = "meetings"

    teams_meeting_id: str           # from Graph API onlineMeetingId
    thread_id: str                  # Teams chat thread ID
    join_url: str                   # Teams meeting join URL
    subject: str
    organizer_id: str               # Azure AD user ID of organizer
    organizer_name: str
    organizer_email: str
    scheduled_start: datetime       # UTC
    scheduled_end: datetime         # UTC
    actual_start: datetime | None
    actual_end: datetime | None
    status: str                     # "scheduled", "in_progress", "completed", "failed", "cancelled"
    acs_call_connection_id: str | None  # ACS call connection ID once joined
    participant_count: int = 0

    # Relationships
    participants: list["MeetingParticipant"]
    transcript_segments: list["TranscriptSegment"]
    summary: "MeetingSummary" | None
    action_items: list["ActionItem"]


class MeetingParticipant(Base, TimestampMixin):
    __tablename__ = "meeting_participants"

    meeting_id: UUID               # FK -> meetings.id
    user_id: str | None            # Azure AD user ID (null if external)
    display_name: str
    email: str | None
    role: str                      # "organizer", "attendee", "presenter"
    joined_at: datetime | None
    left_at: datetime | None
```

### `transcript.py`
```python
class TranscriptSegment(Base, TimestampMixin):
    __tablename__ = "transcript_segments"

    meeting_id: UUID               # FK -> meetings.id
    speaker_name: str
    speaker_id: str | None         # ACS participant ID
    text: str
    start_time: float              # seconds from meeting start
    end_time: float
    confidence: float | None       # 0.0 - 1.0
    sequence_number: int           # ordering
```

### `summary.py`
```python
class MeetingSummary(Base, TimestampMixin):
    __tablename__ = "meeting_summaries"

    meeting_id: UUID               # FK -> meetings.id (one-to-one)
    summary_text: str              # 3-5 paragraph summary
    decisions: list[dict]          # JSON: [{"decision": "...", "context": "..."}]
    key_topics: list[dict]         # JSON: [{"topic": "...", "timestamp": "...", "detail": "..."}]
    unresolved_questions: list[str] # JSON array
    model_used: str                # e.g. "gpt-4o-mini"
    processing_time_seconds: float
    delivered: bool = False
    delivered_at: datetime | None
```

### `action_item.py`
```python
class ActionItem(Base, TimestampMixin):
    __tablename__ = "action_items"

    meeting_id: UUID               # FK -> meetings.id
    description: str
    assigned_to_name: str          # raw name from transcript
    assigned_to_user_id: str | None  # resolved Azure AD user ID
    assigned_to_email: str | None
    deadline: datetime | None
    priority: str                  # "high", "medium", "low"
    status: str                    # "pending", "in_progress", "completed", "snoozed"
    nudge_count: int = 0           # how many nudges sent
    last_nudged_at: datetime | None
    completed_at: datetime | None
    snoozed_until: datetime | None
    source_quote: str | None       # exact transcript quote where this was mentioned
```

### `subscription.py`
```python
class GraphSubscription(Base, TimestampMixin):
    __tablename__ = "graph_subscriptions"

    subscription_id: str           # Graph subscription ID
    user_id: str                   # Azure AD user ID being watched
    resource: str                  # e.g. "/users/{id}/events"
    expiration: datetime
    status: str                    # "active", "expired", "failed"


class UserPreference(Base, TimestampMixin):
    __tablename__ = "user_preferences"

    user_id: str                   # Azure AD user ID
    display_name: str
    email: str
    opted_in: bool = True
    summary_delivery: str = "chat"  # "chat", "email", "both"
    nudge_enabled: bool = True
```

---

## 6. Service Implementations

### 6.1 Auth Utility (`app/utils/auth.py`)

Use MSAL (Microsoft Authentication Library) to acquire tokens for Graph API and ACS.

```python
from msal import ConfidentialClientApplication

class TokenProvider:
    def __init__(self, tenant_id, client_id, client_secret):
        self.app = ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )

    async def get_graph_token(self) -> str:
        """Acquire token for Microsoft Graph API."""
        result = self.app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" in result:
            return result["access_token"]
        raise Exception(f"Token acquisition failed: {result.get('error_description')}")

    async def get_acs_token(self) -> str:
        """Acquire token for ACS if needed (usually connection string is sufficient)."""
        # ACS typically uses connection string auth, not MSAL
        # This method is here if you switch to Entra ID auth for ACS later
        pass
```

### 6.2 Graph Client (`app/services/graph_client.py`)

Wrap all Microsoft Graph API calls. Use `httpx.AsyncClient` for async HTTP.

Implement these methods:

```python
class GraphClient:
    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, token_provider: TokenProvider):
        self.token_provider = token_provider
        self.http = httpx.AsyncClient(timeout=30)

    async def _headers(self) -> dict:
        token = await self.token_provider.get_graph_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # --- Calendar Subscriptions ---

    async def create_calendar_subscription(self, user_id: str, webhook_url: str) -> dict:
        """
        POST /subscriptions
        Subscribe to calendar event changes for a user.
        Resource: /users/{user_id}/events
        Change types: created, updated, deleted
        Expiration: max 3 days for calendar events — must renew before expiry.
        """
        pass

    async def renew_subscription(self, subscription_id: str, new_expiration: datetime) -> dict:
        """PATCH /subscriptions/{id} — extend expiration."""
        pass

    async def delete_subscription(self, subscription_id: str) -> None:
        """DELETE /subscriptions/{id}"""
        pass

    # --- Calendar Events ---

    async def get_event(self, user_id: str, event_id: str) -> dict:
        """GET /users/{user_id}/events/{event_id} — get full event details including joinWebUrl."""
        pass

    async def get_upcoming_events(self, user_id: str, hours_ahead: int = 24) -> list[dict]:
        """
        GET /users/{user_id}/calendarView
        Params: startDateTime, endDateTime
        Filter for events that have an onlineMeeting joinUrl (isOnlineMeeting eq true).
        """
        pass

    # --- Meeting Details ---

    async def get_online_meeting(self, meeting_id: str) -> dict:
        """GET /communications/onlineMeetings/{meetingId} — meeting metadata."""
        pass

    async def get_meeting_participants(self, call_id: str) -> list[dict]:
        """GET /communications/calls/{callId}/participants"""
        pass

    # --- Chat & Messaging ---

    async def post_to_meeting_chat(self, thread_id: str, adaptive_card: dict) -> dict:
        """
        POST /chats/{threadId}/messages
        Content type: application/vnd.microsoft.card.adaptive
        This is how we deliver the post-meeting summary and nudges.
        """
        pass

    async def send_proactive_message(self, user_id: str, adaptive_card: dict) -> dict:
        """
        Send a 1:1 proactive message to a user via Bot Framework.
        Used for nudge reminders.
        Requires: the bot must have had a prior conversation with the user,
        OR you use the Graph API to send to the user's chat with the bot.
        """
        pass

    # --- User Resolution ---

    async def search_user(self, display_name: str) -> list[dict]:
        """
        GET /users?$filter=startswith(displayName, '{name}')
        Used for fuzzy matching action item owners to real users.
        """
        pass

    async def get_user(self, user_id: str) -> dict:
        """GET /users/{user_id} — get display name, email, etc."""
        pass
```

### 6.3 Calendar Watcher (`app/services/calendar_watcher.py`)

This service:

1. On startup, creates Graph change notification subscriptions for all opted-in users
2. Receives webhook callbacks when calendar events are created/updated/deleted
3. Extracts the Teams meeting join URL from the event
4. Schedules the ACS bot to join N minutes before the meeting start time
5. Handles subscription renewal (max lifetime is ~3 days for calendar events)

```python
class CalendarWatcher:
    def __init__(self, graph_client: GraphClient, db: AsyncSession, scheduler, settings: Settings):
        self.graph = graph_client
        self.db = db
        self.scheduler = scheduler
        self.settings = settings

    async def setup_subscriptions(self):
        """
        Called on app startup.
        For each opted-in user, create a Graph subscription on their calendar.
        Store subscription IDs in DB for renewal tracking.
        """
        pass

    async def handle_webhook(self, payload: dict) -> None:
        """
        Called by the webhook route when Graph sends a change notification.

        Payload structure (Graph change notification):
        {
            "value": [{
                "subscriptionId": "...",
                "changeType": "created" | "updated" | "deleted",
                "resource": "users/{userId}/events/{eventId}",
                "resourceData": { "@odata.id": "...", "id": "..." }
            }]
        }

        Steps:
        1. Extract event ID from the notification
        2. Call Graph to get full event details
        3. Check if it's a Teams meeting (has joinWebUrl)
        4. If new meeting: store in DB, schedule bot join
        5. If updated: update DB, reschedule if time changed
        6. If deleted: cancel scheduled join, update DB status
        """
        pass

    async def schedule_bot_join(self, meeting: Meeting) -> None:
        """
        Schedule the ACS bot to join the meeting X minutes before start.
        Use APScheduler to add a one-time job.
        Job calls acs_call_service.join_meeting(meeting).
        """
        pass

    async def renew_subscriptions(self) -> None:
        """
        Periodic task (run every 12 hours).
        Query DB for subscriptions expiring within 6 hours.
        Renew each one via Graph API.
        If renewal fails, recreate the subscription.
        """
        pass
```

**IMPORTANT: Graph webhook validation.** When you first create a subscription, Graph sends a validation request to your webhook URL with a `validationToken` query parameter. You must respond with 200 OK and the token as plain text body. Implement this in the webhook route.

### 6.4 ACS Call Service (`app/services/acs_call_service.py`)

This is the **core service**. It uses Azure Communication Services Call Automation to join Teams meetings and capture audio/transcription independently.

```python
from azure.communication.callautomation import (
    CallAutomationClient,
    MediaStreamingOptions,
    MediaStreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    TranscriptionOptions,
    TranscriptionTransportType,
)

class ACSCallService:
    def __init__(self, settings: Settings, db: AsyncSession):
        self.client = CallAutomationClient.from_connection_string(
            settings.ACS_CONNECTION_STRING
        )
        self.settings = settings
        self.db = db

    async def join_meeting(self, meeting: Meeting) -> str:
        """
        Join a Teams meeting using ACS Call Automation.

        CRITICAL IMPLEMENTATION DETAILS:
        1. Use the meeting's join_url (Teams meeting link)
        2. Configure media streaming to send audio to our WebSocket endpoint
        3. Configure transcription to send real-time transcription to our WebSocket endpoint
        4. ACS joins as a participant — audio capture is independent of Teams transcription settings

        Returns: call_connection_id

        Code pattern:
        ```
        call_connection_properties = self.client.create_group_call(
            target_participant=meeting.join_url,   # The Teams meeting join link
            callback_url=f"{self.settings.BASE_URL}/callbacks/acs",
            media_streaming=MediaStreamingOptions(
                transport_url=f"wss://{self.settings.BASE_URL}/ws/audio/{meeting.id}",
                transport_type=MediaStreamingTransportType.WEBSOCKET,
                content_type=MediaStreamingContentType.AUDIO,
                audio_channel_type=MediaStreamingAudioChannelType.UNMIXED,
            ),
            transcription=TranscriptionOptions(
                transport_url=f"wss://{self.settings.BASE_URL}/ws/transcription/{meeting.id}",
                transport_type=TranscriptionTransportType.WEBSOCKET,
                locale="en-US",
            ),
        )
        ```

        After joining:
        - Update meeting.status = "in_progress"
        - Update meeting.acs_call_connection_id
        - Update meeting.actual_start = now
        """
        pass

    async def handle_callback(self, event: dict) -> None:
        """
        Handle ACS Call Automation callback events.

        Key events to handle:
        - CallConnected: bot successfully joined the meeting
        - CallDisconnected: meeting ended or bot was removed
        - ParticipantsUpdated: someone joined/left (update participant list)
        - TranscriptionStarted: transcription stream is active
        - TranscriptionStopped: transcription stream ended
        - MediaStreamingStarted: audio stream is active
        - MediaStreamingStopped: audio stream ended
        - PlayCompleted / PlayFailed: if we play announcements

        On CallDisconnected:
        1. Update meeting.status = "completed", meeting.actual_end = now
        2. Trigger the post-meeting processing pipeline:
           - Assemble full transcript from DB
           - Send to AI processor
           - Deliver summary
        """
        pass

    async def leave_meeting(self, call_connection_id: str) -> None:
        """Gracefully leave the meeting. Called if meeting runs too long or on error."""
        call_connection = self.client.get_call_connection(call_connection_id)
        call_connection.hang_up(is_for_everyone=False)

    async def start_transcription(self, call_connection_id: str) -> None:
        """Explicitly start transcription if not auto-started."""
        call_connection = self.client.get_call_connection(call_connection_id)
        call_connection.start_transcription(locale="en-US")

    async def stop_transcription(self, call_connection_id: str) -> None:
        """Stop transcription before leaving."""
        call_connection = self.client.get_call_connection(call_connection_id)
        call_connection.stop_transcription()
```

### 6.5 Transcription WebSocket Handler (`app/services/transcription.py`)

Receives real-time transcription data from ACS via WebSocket.

```python
class TranscriptionHandler:
    """
    WebSocket endpoint that receives real-time transcription from ACS.

    ACS sends JSON messages with this structure:
    {
        "kind": "TranscriptionData",
        "transcriptionData": {
            "text": "Hello everyone, let's get started.",
            "format": "display",
            "confidence": 0.95,
            "offset": 1234567890,
            "duration": 5000000,     # in ticks (100ns units)
            "words": [...],
            "participantRawID": "8:acs:...",
            "resultStatus": "Final"  # or "Intermediate"
        }
    }

    Also handles:
    - "TranscriptionMetadata": connection info, call ID
    - "WordData": individual word-level data

    Implementation:
    1. Accept WebSocket connection at /ws/transcription/{meeting_id}
    2. Parse each incoming message
    3. For "Final" results only (skip "Intermediate" to avoid duplicates):
       a. Create a TranscriptSegment record in DB
       b. Resolve speaker name from participant ID
       c. Increment sequence_number
    4. On WebSocket close: mark transcription complete for this meeting
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.active_sessions: dict[str, list] = {}  # meeting_id -> segments buffer

    async def handle_connection(self, websocket, meeting_id: str):
        """Main WebSocket handler — runs for the duration of the meeting."""
        pass
```

### 6.6 AI Processor (`app/services/ai_processor.py`)

Sends transcripts to Azure AI Foundry for intelligent extraction.

```python
from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential

class AIProcessor:
    def __init__(self, settings: Settings):
        self.client = ChatCompletionsClient(
            endpoint=settings.AI_FOUNDRY_ENDPOINT,
            credential=AzureKeyCredential(settings.AI_FOUNDRY_API_KEY),
        )
        self.settings = settings

    async def process_meeting(self, meeting: Meeting, transcript_segments: list[TranscriptSegment]) -> dict:
        """
        Process a complete meeting transcript.

        Steps:
        1. Format transcript into readable text:
           [HH:MM:SS] Speaker Name: Text
           [HH:MM:SS] Speaker Name: Text
           ...

        2. Choose model based on meeting length:
           - < LONG_MEETING_THRESHOLD_MINUTES: use gpt-4o-mini (cheap, fast)
           - >= LONG_MEETING_THRESHOLD_MINUTES: use chunked processing with gpt-4o

        3. Send to AI Foundry with the extraction prompt (see below)

        4. Parse the JSON response into MeetingSummary + ActionItem records

        5. Return structured data

        IMPORTANT: For long meetings (>2 hours), implement chunked summarization:
        - Split transcript into 30-minute chunks
        - Summarize each chunk independently
        - Then do a final "summary of summaries" pass
        """
        pass

    def _build_extraction_prompt(self, transcript: str, meeting_subject: str, participants: list[str]) -> str:
        """
        Build the system + user prompt for the LLM.

        System prompt:
        "You are a meeting analyst. You will receive a meeting transcript and must extract structured information.
        Respond ONLY with valid JSON matching the schema below. Do not include any other text.

        JSON Schema:
        {
            "summary": "3-5 paragraph summary of the meeting, covering all key points discussed",
            "action_items": [
                {
                    "description": "Clear description of what needs to be done",
                    "assigned_to": "Person's name as mentioned in the transcript",
                    "deadline": "ISO 8601 date if mentioned, null otherwise",
                    "priority": "high | medium | low",
                    "source_quote": "Exact quote from transcript where this was discussed"
                }
            ],
            "decisions": [
                {
                    "decision": "What was decided",
                    "context": "Brief context of why/how this decision was reached"
                }
            ],
            "key_topics": [
                {
                    "topic": "Topic name",
                    "timestamp": "Approximate timestamp when discussed",
                    "detail": "Brief description of what was discussed about this topic"
                }
            ],
            "unresolved_questions": [
                "Question or issue that was raised but not resolved"
            ]
        }"

        User prompt:
        "Meeting Subject: {subject}
        Participants: {comma-separated participant names}

        Transcript:
        {formatted transcript}"
        """
        pass

    async def _process_chunked(self, meeting: Meeting, transcript_segments: list) -> dict:
        """
        For long meetings:
        1. Split into 30-minute chunks
        2. Summarize each chunk
        3. Combine chunk summaries into final summary
        4. Merge and deduplicate action items across chunks
        """
        pass
```

### 6.7 Owner Resolver (`app/services/owner_resolver.py`)

Matches names extracted by the LLM to actual Azure AD users.

```python
class OwnerResolver:
    def __init__(self, graph_client: GraphClient):
        self.graph = graph_client

    async def resolve(self, name: str, participants: list[MeetingParticipant]) -> tuple[str | None, str | None]:
        """
        Resolve a name mentioned in the transcript to a real user.

        Strategy:
        1. Exact match against meeting participant display names (case-insensitive)
        2. Partial match: check if the name is a first name of any participant
           e.g., "John" matches "John Smith"
        3. If no participant match, search Graph API: GET /users?$filter=startswith(displayName, '{name}')
        4. If still no match, return (None, None) — the UI can handle unresolved owners

        Returns: (user_id, email) or (None, None)

        Use rapidfuzz or thefuzz for fuzzy matching if exact/partial fails.
        """
        pass
```

### 6.8 Delivery Service (`app/services/delivery.py`)

Posts Adaptive Cards to Teams.

```python
class DeliveryService:
    def __init__(self, graph_client: GraphClient, settings: Settings):
        self.graph = graph_client
        self.settings = settings

    async def deliver_summary(self, meeting: Meeting, summary: MeetingSummary, action_items: list[ActionItem]) -> None:
        """
        Post the meeting summary as an Adaptive Card to the meeting's Teams chat.

        Steps:
        1. Load the summary_card.json template
        2. Populate it with:
           - Meeting title and date
           - Duration
           - Summary text
           - Action items table (description, owner, deadline, priority)
           - Decisions list
           - Link to full transcript (if you have a UI route for this)
        3. Post to meeting chat via graph_client.post_to_meeting_chat(meeting.thread_id, card)
        4. Update summary.delivered = True, summary.delivered_at = now
        """
        pass

    async def send_nudge(self, action_item: ActionItem) -> None:
        """
        Send a 1:1 nudge to the action item owner.

        Use the nudge_card.json template with:
        - Action item description
        - Meeting it came from
        - Deadline
        - Buttons: "Complete", "Snooze 1 Day", "Update Status"

        Post via graph_client.send_proactive_message(action_item.assigned_to_user_id, card)
        Update action_item.nudge_count += 1, action_item.last_nudged_at = now
        """
        pass

    async def send_escalation(self, action_item: ActionItem, meeting: Meeting) -> None:
        """
        After NUDGE_ESCALATION_THRESHOLD missed nudges, notify the meeting organizer.
        """
        pass
```

### 6.9 Nudge Scheduler (`app/services/nudge_scheduler.py`)

Runs periodically to check for action items that need nudging.

```python
class NudgeScheduler:
    """
    Runs every NUDGE_CHECK_INTERVAL_MINUTES (default: 30 min).

    Logic:
    1. Query action items where:
       - status is "pending" or "in_progress"
       - AND (deadline is within 24 hours OR deadline has passed)
       - AND (last_nudged_at is NULL or last_nudged_at < now - 4 hours)  # don't spam
       - AND snoozed_until is NULL or snoozed_until < now
    2. For each item:
       a. If nudge_count >= NUDGE_ESCALATION_THRESHOLD: send escalation to organizer
       b. Else: send nudge to assignee
    3. Update nudge tracking fields
    """

    def __init__(self, delivery: DeliveryService, db: AsyncSession, settings: Settings):
        self.delivery = delivery
        self.db = db
        self.settings = settings

    async def run(self) -> None:
        """Main scheduler tick. Called by APScheduler or Celery beat."""
        pass
```

---

## 7. API Routes

### 7.1 Webhook Routes (`app/routes/webhooks.py`)

```python
@router.post("/webhooks/graph")
async def graph_webhook(request: Request, calendar_watcher: CalendarWatcher = Depends(...)):
    """
    Receives Microsoft Graph change notifications.

    IMPORTANT: Graph webhook validation flow:
    1. On subscription creation, Graph sends GET with ?validationToken=xxx
       → Respond 200 with the token as plain text
    2. On actual changes, Graph sends POST with JSON payload
       → Validate the request (check clientState if configured)
       → Process notification
       → Respond 202 Accepted within 3 seconds (process async)
    """
    # Handle validation
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        return PlainTextResponse(content=validation_token, status_code=200)

    # Handle notification
    payload = await request.json()
    # Process in background to respond within 3 seconds
    background_tasks.add_task(calendar_watcher.handle_webhook, payload)
    return Response(status_code=202)
```

### 7.2 ACS Callback Routes (`app/routes/acs_callbacks.py`)

```python
@router.post("/callbacks/acs")
async def acs_callback(request: Request, acs_service: ACSCallService = Depends(...)):
    """
    Receives ACS Call Automation event callbacks.

    Events arrive as CloudEvents format.
    Parse and route to acs_service.handle_callback().
    """
    events = await request.json()
    for event in events:
        await acs_service.handle_callback(event)
    return Response(status_code=200)
```

### 7.3 WebSocket Routes (in `app/main.py` or separate)

```python
@app.websocket("/ws/transcription/{meeting_id}")
async def transcription_ws(websocket: WebSocket, meeting_id: str):
    """
    WebSocket endpoint that ACS connects to for streaming transcription data.
    Delegates to TranscriptionHandler.
    """
    await websocket.accept()
    handler = TranscriptionHandler(db=get_db())
    await handler.handle_connection(websocket, meeting_id)
```

### 7.4 Meeting Routes (`app/routes/meetings.py`) — for the UI

```python
@router.get("/meetings")
async def list_meetings(status: str | None = None, limit: int = 20, offset: int = 0):
    """List meetings, optionally filtered by status. For the UI dashboard."""
    pass

@router.get("/meetings/{meeting_id}")
async def get_meeting(meeting_id: UUID):
    """Get full meeting details including summary and action items."""
    pass

@router.get("/meetings/{meeting_id}/transcript")
async def get_transcript(meeting_id: UUID):
    """Get the full transcript for a meeting."""
    pass

@router.post("/meetings/{meeting_id}/reprocess")
async def reprocess_meeting(meeting_id: UUID):
    """Re-run AI processing on an existing transcript (e.g., after prompt changes)."""
    pass
```

### 7.5 Action Item Routes (`app/routes/action_items.py`) — for the UI

```python
@router.get("/action-items")
async def list_action_items(status: str | None = None, user_id: str | None = None):
    """List action items, filterable by status and assignee."""
    pass

@router.patch("/action-items/{item_id}")
async def update_action_item(item_id: UUID, update: ActionItemUpdate):
    """Update status, snooze, mark complete. Called by Adaptive Card button actions too."""
    pass

@router.post("/action-items/{item_id}/complete")
async def complete_action_item(item_id: UUID):
    """Mark an action item as completed."""
    pass

@router.post("/action-items/{item_id}/snooze")
async def snooze_action_item(item_id: UUID, days: int = 1):
    """Snooze nudges for N days."""
    pass
```

### 7.6 Health Route (`app/routes/health.py`)

```python
@router.get("/health")
async def health():
    """Health check for Azure Container Apps probes."""
    return {"status": "healthy", "service": "teams-meeting-assistant"}
```

---

## 8. Adaptive Card Templates

### `templates/summary_card.json`

Create a rich Adaptive Card (schema version 1.5) with:

- **Header**: Meeting title, date/time, duration, participant count
- **Summary section**: Collapsible text block with the AI-generated summary
- **Action Items table**: Table with columns: Description, Owner, Deadline, Priority
- **Decisions list**: Bullet list of decisions made
- **Footer**: "Powered by Meeting Assistant" + link to full transcript

Use `Action.ToggleVisibility` for collapsible sections. Use `ColumnSet` for the table layout.

### `templates/nudge_card.json`

- **Header**: "Action Item Reminder"
- **Body**: Description of the action item, which meeting it came from, deadline
- **Actions**:
  - `Action.Submit` with data `{"action": "complete", "item_id": "..."}` — label "Mark Complete"
  - `Action.Submit` with data `{"action": "snooze", "item_id": "...", "days": 1}` — label "Snooze 1 Day"
  - `Action.Submit` with data `{"action": "update", "item_id": "..."}` — label "Update Status"

### `templates/weekly_digest_card.json`

- Summary of all meetings from the past week
- Open action items grouped by assignee
- Completion rate statistics

---

## 9. Main Application Entry Point (`app/main.py`)

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
    1. Initialize DB connection pool (SQLAlchemy async engine)
    2. Run Alembic migrations (or verify DB is up to date)
    3. Initialize service instances (GraphClient, ACSCallService, etc.)
    4. Start APScheduler with:
       a. Nudge scheduler: runs every NUDGE_CHECK_INTERVAL_MINUTES
       b. Subscription renewal: runs every 12 hours
    5. Call calendar_watcher.setup_subscriptions() to start watching calendars

    Shutdown:
    1. Stop scheduler
    2. Leave any active meetings gracefully
    3. Close DB connections
    4. Close HTTP client sessions
    """
    # startup
    yield
    # shutdown

app = FastAPI(
    title="Teams Meeting Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(acs_callbacks_router, prefix="/callbacks", tags=["acs"])
app.include_router(meetings_router, prefix="/api/meetings", tags=["meetings"])
app.include_router(action_items_router, prefix="/api/action-items", tags=["action-items"])
app.include_router(health_router, tags=["health"])

# WebSocket routes registered directly on app (see section 7.3)
```

---

## 10. Deployment

### `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

**NOTE:** Use `--workers 1` because we need WebSocket connections to stay on the same process. For horizontal scaling, use Azure Container Apps replicas with sticky sessions.

### `docker-compose.yml` (local development)

```yaml
version: "3.8"
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - postgres
      - redis
    volumes:
      - ./app:/app/app  # hot reload

  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: assistant
      POSTGRES_PASSWORD: localdev
      POSTGRES_DB: meeting_assistant
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  pgdata:
```

### `.env.example`

```env
# App
DEBUG=true
BASE_URL=https://your-ngrok-or-tunnel-url.ngrok.io

# Database
DATABASE_URL=postgresql+asyncpg://assistant:localdev@localhost:5432/meeting_assistant

# Microsoft Entra ID
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-app-client-id
AZURE_CLIENT_SECRET=your-client-secret

# Azure Communication Services
ACS_CONNECTION_STRING=endpoint=https://your-acs.communication.azure.com/;accesskey=...
ACS_ENDPOINT=https://your-acs.communication.azure.com

# Azure AI Foundry
AI_FOUNDRY_ENDPOINT=https://your-resource.openai.azure.com/
AI_FOUNDRY_API_KEY=your-api-key
AI_FOUNDRY_DEPLOYMENT_NAME=gpt-4o-mini
AI_FOUNDRY_DEPLOYMENT_NAME_COMPLEX=gpt-4o

# Redis
REDIS_URL=redis://localhost:6379/0

# Bot Behavior
BOT_DISPLAY_NAME=Meeting Assistant
BOT_JOIN_BEFORE_MINUTES=1
NUDGE_CHECK_INTERVAL_MINUTES=30
```

---

## 11. `requirements.txt`

```
# Web Framework
fastapi==0.115.*
uvicorn[standard]==0.34.*

# Database
sqlalchemy[asyncio]==2.0.*
asyncpg==0.30.*
alembic==1.14.*

# Microsoft SDKs
azure-communication-callautomation==1.3.*
azure-identity==1.19.*
msal==1.31.*
azure-ai-inference==1.0.*

# HTTP Client
httpx==0.28.*

# Task Scheduling
apscheduler==3.10.*

# Pydantic
pydantic==2.10.*
pydantic-settings==2.7.*

# Utilities
python-dotenv==1.0.*
rapidfuzz==3.10.*          # fuzzy name matching
tenacity==9.0.*            # retry logic
python-json-logger==3.2.*  # structured logging

# Redis (optional, for Celery)
redis==5.2.*
```

### `requirements-dev.txt`

```
-r requirements.txt
pytest==8.3.*
pytest-asyncio==0.24.*
httpx==0.28.*             # for TestClient
factory-boy==3.3.*
faker==33.*
```

---

## 12. Scripts

### `scripts/setup_acs_federation.ps1`

```powershell
# Run this ONCE in your Teams admin PowerShell to enable ACS-Teams interop.
# Requires Teams Administrator role.

Install-Module -Name MicrosoftTeams -Force -AllowClobber
Connect-MicrosoftTeams

# Enable ACS federation so ACS users can join Teams meetings
Set-CsTeamsAcsFederationConfiguration -EnableAcsUsers $true

# Verify
Get-CsTeamsAcsFederationConfiguration

Write-Host "ACS federation enabled. ACS bots can now join Teams meetings."
```

### `scripts/grant_graph_permissions.sh`

```bash
#!/bin/bash
# Grant admin consent for Graph API permissions.
# Requires: az cli logged in as tenant admin.

APP_ID="your-app-client-id"
TENANT_ID="your-tenant-id"

echo "Opening admin consent URL in browser..."
echo "Sign in as a tenant admin and grant consent."
echo ""

URL="https://login.microsoftonline.com/${TENANT_ID}/adminconsent?client_id=${APP_ID}&redirect_uri=https://localhost"
echo "$URL"

# On macOS:
# open "$URL"
# On Linux:
# xdg-open "$URL"
```

---

## 13. Testing Strategy

Write tests for every service. Use pytest-asyncio.

### Key test scenarios:

1. **Calendar Watcher**
   - Webhook validation (returns validationToken)
   - New meeting created → stored in DB + join scheduled
   - Meeting updated (time change) → reschedule join
   - Meeting deleted → cancel join

2. **ACS Call Service**
   - Join meeting → returns call_connection_id
   - CallDisconnected event → triggers post-processing
   - Handle concurrent meetings

3. **AI Processor**
   - Short meeting → uses gpt-4o-mini
   - Long meeting → uses chunked processing
   - Malformed LLM response → graceful error handling
   - JSON parsing of LLM output

4. **Owner Resolver**
   - Exact name match against participants
   - First-name-only match
   - No match → returns None

5. **Nudge Scheduler**
   - Items approaching deadline → nudge sent
   - Items past escalation threshold → escalation sent
   - Snoozed items → skipped until snooze expires
   - Completed items → not nudged

### Mock strategy:
- Mock `httpx.AsyncClient` for Graph API calls
- Mock `CallAutomationClient` for ACS calls
- Mock `ChatCompletionsClient` for AI Foundry calls
- Use an in-memory SQLite or test PostgreSQL for DB tests

---

## 14. Development Order

Build and test in this exact order:

### Phase 1: Foundation (do first)
1. `config.py` — settings loaded from env
2. `models/` — all database models
3. Alembic setup + initial migration
4. `main.py` — bare FastAPI app with health route
5. `docker-compose.yml` — verify app + postgres start
6. `utils/auth.py` — token acquisition

### Phase 2: Calendar + Meeting Detection
7. `services/graph_client.py` — implement calendar methods
8. `services/calendar_watcher.py` — subscription + webhook handling
9. `routes/webhooks.py` — Graph webhook endpoint
10. Test: create subscription, receive webhook, meeting stored in DB

### Phase 3: ACS Join + Transcription (CORE)
11. `services/acs_call_service.py` — join meeting via ACS
12. `services/transcription.py` — WebSocket handler for transcription
13. `routes/acs_callbacks.py` — ACS event callbacks
14. WebSocket route for transcription
15. Test: bot joins a real Teams meeting, transcription flows into DB

### Phase 4: AI Processing
16. `services/ai_processor.py` — prompt building + AI Foundry call
17. `services/owner_resolver.py` — name resolution
18. Test: feed a transcript, get structured summary + action items

### Phase 5: Delivery + Nudges
19. `templates/` — all Adaptive Card JSON templates
20. `services/delivery.py` — post cards to Teams chat
21. `services/nudge_scheduler.py` — periodic nudge logic
22. `routes/action_items.py` — CRUD for UI
23. Test: summary card appears in Teams, nudges fire on schedule

### Phase 6: Polish
24. `routes/meetings.py` — full CRUD for UI
25. Error handling + retry logic everywhere
26. Structured logging
27. Dockerfile + deployment configs
28. End-to-end test: meeting scheduled → bot joins → transcript → summary → nudge

---

## 15. Critical Gotchas

1. **ACS Federation MUST be enabled** — without `Set-CsTeamsAcsFederationConfiguration -EnableAcsUsers $true`, the bot cannot join Teams meetings. This is a PowerShell command run by a Teams admin, not code.

2. **Graph webhook validation** — Graph sends a GET with `validationToken` when you create a subscription. You must echo it back as plain text 200 response. If you miss this, the subscription silently fails.

3. **Graph subscription expiry** — Calendar subscriptions expire after ~3 days. You MUST renew them proactively. If they expire, you stop getting notifications silently.

4. **ACS joins as external participant** — The bot appears as "[Bot Name] (External)" in the meeting. This is expected behavior. It still captures all audio.

5. **WebSocket URL must be publicly accessible** — ACS needs to connect TO your WebSocket endpoint. During local dev, use ngrok or Azure Dev Tunnels to expose it.

6. **Token caching** — MSAL handles token caching internally. Don't manually cache tokens — use the same `ConfidentialClientApplication` instance throughout the app lifecycle.

7. **Long meetings + LLM context** — GPT-4o-mini has 128K context. A 1-hour meeting transcript is roughly 10-15K tokens. You'll only need chunking for very long meetings (3+ hours).

8. **Adaptive Card schema version** — Teams supports up to schema version 1.5. Don't use 1.6+ features.

9. **Rate limits** — Graph API has per-tenant throttling. Implement retry with exponential backoff (use Tenacity). ACS has its own rate limits for call operations.

10. **Bot must be registered in Azure Bot Service** — even though ACS handles the call, you still need an Azure Bot Service registration for the Teams channel to send proactive messages and Adaptive Cards.

---

## 16. Environment Setup Checklist (Before Writing Code)

Run these setup steps before starting development:

- [ ] Azure subscription active
- [ ] Microsoft Entra ID app registration created
- [ ] Graph API permissions added and admin consent granted
- [ ] Azure Communication Services resource created
- [ ] ACS-Teams federation enabled (PowerShell)
- [ ] Azure AI Foundry resource created with gpt-4o-mini deployed
- [ ] Azure Bot Service created and linked to app registration
- [ ] Teams channel enabled on Bot Service
- [ ] PostgreSQL database provisioned (local Docker for dev)
- [ ] SSL certificate / tunnel (ngrok) for local webhook testing
- [ ] `.env` file populated with all credentials
