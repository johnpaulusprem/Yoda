# Teams Meeting Assistant Bot — Backend Development Specification

## For Claude Code: Build this project following every instruction below exactly.

---

## 1. Project Overview

Build the **complete backend** for a Teams Meeting Assistant Bot using a **hybrid architecture**:

- **Service A — Media Bot (C#/.NET)**: A minimal Application-Hosted Media Bot that joins Teams meetings via the Microsoft Graph Cloud Communications API, captures raw audio frames using the Real-Time Media SDK, and forwards them to Service B. This is the only component that MUST be C#/.NET on Windows Server — Microsoft's SDK constraint.
- **Service B — Brain (Python/FastAPI)**: Everything else — calendar watching, transcription orchestration, AI processing, summary delivery, nudges, database, and API for the UI. This is where all the intelligence lives.

**Why hybrid?** The Real-Time Media SDK (`Microsoft.Skype.Bots.Media`) is a native Windows DLL. It only works with C#/.NET on Windows Server. There is no Python, Node.js, or Linux alternative for capturing raw audio from Teams meetings. But everything *after* audio capture has no such constraint, so we keep the C# footprint minimal and do the rest in Python where it's cheaper and faster to develop.

### What the system does end-to-end:

1. **Calendar Watcher** (Python) monitors user calendars via Graph API subscriptions
2. When a meeting is about to start, Python tells the **Media Bot** (C#) to join
3. Media Bot joins the Teams meeting, receives raw audio frames (50/sec, 20ms each)
4. Media Bot streams audio to **Azure AI Speech** for real-time transcription, or forwards raw audio to the Python service via a message queue
5. Transcription results are stored in PostgreSQL by the Python service
6. After the meeting ends, Python sends the transcript to **Azure AI Foundry** (GPT-4o-mini or GPT-4o) for summary + action item extraction
7. Python delivers the summary as an **Adaptive Card** to the Teams meeting chat via Graph API
8. A **nudge scheduler** (Python) periodically reminds action item owners about upcoming/overdue items

**The UI already exists.** You are building only the backend services and API layer.

---

## 2. Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                    SERVICE B: BRAIN (Python/FastAPI)                  │
│                    Linux · Azure Container Apps · ~$30-60/mo         │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │ Calendar      │  │ Transcript   │  │ AI Processor              │  │
│  │ Watcher       │  │ Store +      │  │ (Azure AI Foundry)        │  │
│  │ (Graph Subs)  │  │ Assembler    │  │ Summary, Actions, etc.    │  │
│  └──────┬───────┘  └──────▲───────┘  └────────────┬──────────────┘  │
│         │                  │                       │                  │
│         │ "join meeting"   │ transcript chunks     │ structured JSON  │
│         ▼                  │                       ▼                  │
│  ┌──────────────┐  ┌──────┴───────┐  ┌───────────────────────────┐  │
│  │ Bot           │  │ Message      │  │ Delivery Service          │  │
│  │ Orchestrator  │  │ Queue        │  │ (Adaptive Cards)          │  │
│  │ (commands to  │  │ (Azure       │  │ + Nudge Scheduler         │  │
│  │  Service A)   │  │ Service Bus) │  │                           │  │
│  └──────┬───────┘  └──────▲───────┘  └───────────────────────────┘  │
│         │                  │                                         │
│         │ HTTP/Queue       │ transcription results                   │
└─────────┼──────────────────┼─────────────────────────────────────────┘
          │                  │
          ▼                  │
┌─────────────────────────────────────────────────────────────────────┐
│              SERVICE A: MEDIA BOT (C#/.NET 8)                        │
│              Windows Server · Azure VMSS or Cloud Service            │
│              ~$150-400/mo                                            │
│                                                                      │
│  ┌──────────────────┐    ┌──────────────────────────────────────┐   │
│  │ Graph Comms SDK   │    │ Audio Frame Handler                  │   │
│  │ Join meeting      │───▶│ 50 frames/sec (20ms PCM each)       │   │
│  │ Receive callbacks │    │                                      │   │
│  └──────────────────┘    │ Option A: Push to Azure Speech SDK   │   │
│                           │   (real-time transcription in-proc)  │   │
│                           │                                      │   │
│                           │ Option B: Forward raw audio chunks   │   │
│                           │   to Service Bus → Python processes  │   │
│                           └──────────────────────────────────────┘   │
│                                                                      │
│  Calls.AccessMedia.All + Calls.JoinGroupCall.All permissions         │
│  Public IP + TCP ports 8445-65535                                    │
│  SSL certificate on domain                                           │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technology Stack

### Service A — Media Bot (C#/.NET)

| Layer | Technology | Reason |
|-------|-----------|--------|
| Language | **C# / .NET 8** | Hard requirement — Real-Time Media SDK is a native Windows DLL |
| OS | **Windows Server 2022** | Required by Media SDK |
| Hosting | **Azure VM Scale Set** (or Cloud Service Extended Support) | Must have public IP + TCP port ranges |
| SDK | **Microsoft.Graph.Communications.Calls.Media** | Joins meetings, receives raw audio frames |
| Transcription | **Azure AI Speech SDK** (in-process) | Real-time speech-to-text with speaker diarization |
| Communication with Service B | **Azure Service Bus** (or HTTP callback) | Forwards transcription results + lifecycle events |

### Service B — Brain (Python)

| Layer | Technology | Reason |
|-------|-----------|--------|
| Language | **Python 3.11+** | Fast development, AI/ML ecosystem |
| Web Framework | **FastAPI** | Async-native, lightweight, OpenAPI docs built-in |
| Database | **PostgreSQL** (Azure Flexible Server) | Low cost, pgvector for future RAG |
| ORM | **SQLAlchemy 2.0** (async with asyncpg) | Industry standard, async support |
| Migrations | **Alembic** | SQLAlchemy's migration companion |
| Task Queue | **APScheduler** | For scheduled nudges and delayed job triggers |
| AI | **Azure AI Foundry** (GPT-4o-mini / GPT-4o) | Summary + action item extraction |
| Message Queue | **Azure Service Bus** | Receives transcription from Service A |
| Hosting | **Azure Container Apps** | Cheapest serverless container option, Linux |

---

## 4. Hard Constraints (imposed by Microsoft — cannot be worked around)

| Constraint | Detail |
|-----------|--------|
| **C#/.NET Only for Media Bot** | The Real-Time Media Platform SDK (`Microsoft.Skype.Bots.Media`) is a native Windows DLL. No Python, Node.js, Java, or Go support. |
| **Windows Server Only** | The media bot MUST run on Windows Server. Linux is NOT supported. |
| **Azure VM/VMSS Required** | Cannot use Azure App Service or Functions for the media bot. Must use VMSS, Cloud Service (Ext. Support), or Service Fabric. |
| **Public IP + TCP Ports** | Each bot instance needs a public IP with TCP port range 8445–65535 open. |
| **NuGet SDK Expires ~Every 3 Months** | `Microsoft.Graph.Communications.Calls.Media` expires. You MUST keep it updated or the bot stops working. |
| **Same Tenant Only** | Bot can only join meetings within its registered tenant (or tenants with admin consent). |
| **Compliance Recording Requirement** | If persisting audio/data derived from audio, you MUST call `updateRecordingStatus` API before recording. Microsoft will block your app otherwise. |

---

## 5. Required Azure AD Permissions

All Application-level (not Delegated). Require tenant admin consent.

| Permission | Purpose |
|-----------|---------|
| **Calls.JoinGroupCall.All** | Join meetings as a bot participant |
| **Calls.AccessMedia.All** | Access raw audio/video streams (**critical** — without it, bot joins but can't hear) |
| **Calls.Initiate.All** | Initiate the join-call request |
| **Calendars.Read** | Read user calendars to find meeting URLs |
| **OnlineMeetings.Read.All** | Read meeting metadata |
| **User.Read.All** | Resolve participant names and emails |
| **Chat.ReadWrite** | Post meeting summaries into chat threads |

---

## 6. Project Structure

### Service A — Media Bot (C#/.NET)

```
MediaBot/
├── MediaBot.sln
├── src/
│   └── MediaBot/
│       ├── Program.cs                     # Host builder, DI setup
│       ├── appsettings.json               # Config (overridden by env vars)
│       ├── appsettings.Development.json
│       │
│       ├── Bot/
│       │   ├── BotService.cs              # IHostedService, manages bot lifecycle
│       │   ├── CallHandler.cs             # Handles Graph Comms call events (joined, updated, terminated)
│       │   ├── MediaSession.cs            # Real-Time Media session management
│       │   └── AudioFrameProcessor.cs     # Receives 50 frames/sec, buffers, sends to Speech SDK
│       │
│       ├── Transcription/
│       │   ├── SpeechTranscriber.cs       # Azure AI Speech SDK integration
│       │   └── TranscriptPublisher.cs     # Publishes transcript segments to Azure Service Bus
│       │
│       ├── Communication/
│       │   ├── ServiceBusPublisher.cs     # Publishes events + transcripts to Service Bus
│       │   └── CommandListener.cs         # Listens for commands from Service B (join, leave, etc.)
│       │
│       ├── Models/
│       │   ├── AudioFrame.cs
│       │   ├── TranscriptSegment.cs
│       │   ├── BotCommand.cs              # join_meeting, leave_meeting, status
│       │   └── BotEvent.cs                # meeting_joined, meeting_ended, error
│       │
│       └── Configuration/
│           ├── BotSettings.cs             # Strongly-typed settings
│           └── AzureAdSettings.cs
│
├── deployment/
│   ├── cloud-service/                     # .cscfg, .csdef (if using Cloud Service)
│   ├── vmss/                              # ARM/Bicep templates for VMSS
│   │   ├── main.bicep
│   │   └── configure-media-ports.ps1
│   └── certificates/
│       └── README.md                      # Instructions for SSL cert setup
│
└── tests/
    └── MediaBot.Tests/
        ├── CallHandlerTests.cs
        ├── AudioFrameProcessorTests.cs
        └── SpeechTranscriberTests.cs
```

### Service B — Brain (Python)

```
brain/
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
│   │   └── bot_events.py          # Service Bus message schemas from Media Bot
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── graph_client.py        # Microsoft Graph API wrapper
│   │   ├── calendar_watcher.py    # Calendar subscription + webhook handler
│   │   ├── bot_orchestrator.py    # Sends join/leave commands to Media Bot via Service Bus
│   │   ├── transcript_consumer.py # Consumes transcript segments from Service Bus
│   │   ├── ai_processor.py        # Azure AI Foundry: summary + action item extraction
│   │   ├── delivery.py            # Post Adaptive Cards to Teams chat
│   │   ├── nudge_scheduler.py     # Scheduled nudge engine
│   │   └── owner_resolver.py      # Fuzzy match names to Graph users
│   │
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── webhooks.py            # POST /webhooks/graph — calendar change notifications
│   │   ├── bot_events.py          # POST /events/bot — fallback HTTP endpoint for bot events
│   │   ├── meetings.py            # GET/POST meeting endpoints for the UI
│   │   ├── action_items.py        # CRUD for action items (UI consumption)
│   │   └── health.py              # GET /health
│   │
│   ├── templates/
│   │   ├── summary_card.json      # Adaptive Card: post-meeting summary
│   │   ├── nudge_card.json        # Adaptive Card: action item nudge
│   │   └── weekly_digest_card.json
│   │
│   └── utils/
│       ├── __init__.py
│       ├── auth.py                # MSAL token acquisition for Graph API
│       ├── logging_config.py      # Structured logging setup
│       └── retry.py               # Tenacity-based retry decorator
│
├── alembic/
│   ├── env.py
│   ├── versions/
│   └── alembic.ini
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_calendar_watcher.py
│   ├── test_bot_orchestrator.py
│   ├── test_transcript_consumer.py
│   ├── test_ai_processor.py
│   ├── test_delivery.py
│   ├── test_nudge_scheduler.py
│   └── test_owner_resolver.py
│
├── deployment/
│   ├── Dockerfile
│   ├── docker-compose.yml         # Local dev: app + postgres + redis
│   └── .env.template
│
├── scripts/
│   ├── setup_acs_federation.ps1   # Not needed anymore — remove from old spec
│   ├── grant_graph_permissions.sh
│   └── seed_db.py
│
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## 7. Inter-Service Communication

The Media Bot (C#) and Brain (Python) communicate via **Azure Service Bus** with two queues:

### Queue 1: `bot-commands` (Python → C#)

Python sends commands telling the Media Bot what to do.

```json
// Join a meeting
{
  "command": "join_meeting",
  "meeting_id": "uuid-from-db",
  "join_url": "https://teams.microsoft.com/l/meetup-join/...",
  "thread_id": "19:meeting_xxxx@thread.v2",
  "organizer_name": "John Smith",
  "subject": "Weekly Standup"
}

// Leave a meeting
{
  "command": "leave_meeting",
  "meeting_id": "uuid-from-db",
  "call_id": "graph-call-id"
}

// Status check
{
  "command": "status",
  "meeting_id": "uuid-from-db"
}
```

### Queue 2: `bot-events` (C# → Python)

The Media Bot sends lifecycle events and transcript data back to Python.

```json
// Bot successfully joined meeting
{
  "event": "meeting_joined",
  "meeting_id": "uuid-from-db",
  "call_id": "graph-call-id",
  "timestamp": "2026-03-03T14:00:00Z"
}

// Transcript segment (real-time, many per meeting)
{
  "event": "transcript_segment",
  "meeting_id": "uuid-from-db",
  "speaker_name": "John Smith",
  "speaker_id": "participant-id",
  "text": "I think we should move the deadline to Friday.",
  "start_time": 125.3,
  "end_time": 129.1,
  "confidence": 0.94,
  "is_final": true,
  "sequence_number": 47
}

// Meeting ended
{
  "event": "meeting_ended",
  "meeting_id": "uuid-from-db",
  "call_id": "graph-call-id",
  "duration_seconds": 3600,
  "timestamp": "2026-03-03T15:00:00Z"
}

// Participant joined/left
{
  "event": "participant_update",
  "meeting_id": "uuid-from-db",
  "participant_name": "Jane Doe",
  "participant_id": "...",
  "action": "joined"  // or "left"
}

// Error
{
  "event": "error",
  "meeting_id": "uuid-from-db",
  "error_code": "7503",
  "error_message": "Permission denied",
  "timestamp": "..."
}
```

---

## 8. Service A — Media Bot Implementation (C#/.NET)

### 8.1 NuGet Packages

```xml
<!-- MediaBot.csproj -->
<ItemGroup>
  <PackageReference Include="Microsoft.Graph.Communications.Calls" Version="1.2.*" />
  <PackageReference Include="Microsoft.Graph.Communications.Calls.Media" Version="1.2.*" />
  <PackageReference Include="Microsoft.Graph.Communications.Common" Version="1.2.*" />
  <PackageReference Include="Microsoft.Skype.Bots.Media" Version="1.2.*" />
  <PackageReference Include="Microsoft.CognitiveServices.Speech" Version="1.42.*" />
  <PackageReference Include="Azure.Messaging.ServiceBus" Version="7.18.*" />
  <PackageReference Include="Microsoft.Identity.Client" Version="4.66.*" />
  <PackageReference Include="Microsoft.Extensions.Hosting" Version="8.0.*" />
  <PackageReference Include="Microsoft.AspNetCore.App" />
</ItemGroup>
```

**CRITICAL:** The `Microsoft.Graph.Communications.Calls.Media` and `Microsoft.Skype.Bots.Media` packages expire approximately every 3 months. Set a calendar reminder to update them. If they expire, the bot silently stops receiving audio.

### 8.2 Configuration (`appsettings.json`)

```json
{
  "Bot": {
    "DisplayName": "Meeting Assistant",
    "AppId": "<from-env>",
    "AppSecret": "<from-env>",
    "TenantId": "<from-env>",
    "PlaceCallEndpointUrl": "https://graph.microsoft.com/v1.0",
    "BotBaseUrl": "https://mediabot.yourdomain.com",
    "MediaPlatformInstancePublicIpAddress": "<public-ip>",
    "MediaPlatformInstanceInternalPort": 8445,
    "ServiceDnsName": "mediabot.yourdomain.com",
    "CertificateThumbprint": "<ssl-cert-thumbprint>"
  },
  "AzureSpeech": {
    "SubscriptionKey": "<from-env>",
    "Region": "eastus",
    "Language": "en-US",
    "EnableDiarization": true
  },
  "ServiceBus": {
    "ConnectionString": "<from-env>",
    "CommandQueue": "bot-commands",
    "EventQueue": "bot-events"
  }
}
```

### 8.3 `BotService.cs` — Bot Lifecycle Manager

```csharp
// This is a hosted service that:
// 1. On startup: initializes the Graph Communications SDK, registers the bot with Graph
// 2. Listens for commands on the "bot-commands" Service Bus queue
// 3. On "join_meeting" command: creates a call via Graph Communications API
// 4. On "leave_meeting" command: hangs up the call
// 5. Manages active call sessions

public class BotService : IHostedService
{
    private readonly ICommunicationsClient _commsClient;
    private readonly ServiceBusProcessor _commandProcessor;
    private readonly ConcurrentDictionary<string, CallSession> _activeCalls;

    // Initialize Graph Communications client:
    // var authProvider = new AuthenticationProvider(appId, appSecret, tenantId);
    // var mediaPlatform = new MediaPlatformSettings { ... };
    // _commsClient = new CommunicationsClientBuilder("bot", settings.BotBaseUrl)
    //     .SetAuthenticationProvider(authProvider)
    //     .SetMediaPlatformSettings(mediaPlatform)
    //     .SetNotificationUrl(new Uri($"{settings.BotBaseUrl}/api/calls"))
    //     .Build();

    // To join a meeting:
    // var joinParams = new JoinMeetingParameters(
    //     chatInfo: new ChatInfo { ThreadId = threadId },
    //     meetingInfo: new OrganizerMeetingInfo { Organizer = new IdentitySet { User = new Identity { Id = organizerId } } },
    //     mediaSession: CreateLocalMediaSession()
    // );
    // joinParams.RequestedModalities = new List<Modality> { Modality.Audio };
    // var call = await _commsClient.Calls().AddAsync(joinParams);
}
```

### 8.4 `AudioFrameProcessor.cs` — Raw Audio Handler

```csharp
// This class subscribes to the audio socket events from the Real-Time Media SDK.
//
// The SDK delivers:
// - ~50 audio frames per second (20ms each)
// - PCM audio data: 16kHz, 16-bit, mono (by default)
// - Unmixed mode: separate streams per participant (for speaker identification)
// - Mixed mode: combined stream of all speakers
//
// USE UNMIXED MODE for transcription with speaker attribution.
//
// Implementation:
// 1. Subscribe to AudioSocket.AudioMediaReceived event
// 2. In the handler, receive AudioMediaBuffer
// 3. Buffer frames (e.g., 500ms-1s worth = 25-50 frames)
// 4. Push buffered audio to Azure Speech SDK's PushAudioInputStream
// 5. Speech SDK returns transcription results with speaker info
//
// CRITICAL: Before processing any audio, call UpdateRecordingStatusAsync:
//   await call.Resource.UpdateRecordingStatusAsync(RecordingStatus.Recording);
// This is a Microsoft compliance requirement. Without it, your app may be blocked.

public class AudioFrameProcessor
{
    private readonly PushAudioInputStream _pushStream;
    private readonly SpeechTranscriber _transcriber;

    public void OnAudioFrameReceived(object sender, AudioMediaBuffer buffer)
    {
        // Extract PCM data from buffer
        // Push to Speech SDK stream
        // buffer.Dispose() when done — these are unmanaged resources, must dispose
    }
}
```

### 8.5 `SpeechTranscriber.cs` — Azure AI Speech Integration

```csharp
// Wraps the Azure AI Speech SDK for real-time continuous recognition.
//
// Configuration:
// - Use PushAudioInputStream (we push audio frames from the media bot)
// - Enable conversation transcription with speaker diarization
// - Language: configurable, default en-US
//
// Key events:
// - Recognized: Final transcription result (use this, not Recognizing)
// - Recognizing: Intermediate result (skip for DB storage, optionally forward for live display)
// - SessionStopped: Transcription session ended
// - Canceled: Error occurred
//
// On each Recognized event:
// 1. Create a TranscriptSegment with speaker name, text, timestamps, confidence
// 2. Publish to Service Bus "bot-events" queue via TranscriptPublisher

public class SpeechTranscriber
{
    private ConversationTranscriber _transcriber;
    private readonly TranscriptPublisher _publisher;

    public async Task StartAsync(PushAudioInputStream audioStream, string meetingId)
    {
        var speechConfig = SpeechConfig.FromSubscription(subscriptionKey, region);
        speechConfig.SpeechRecognitionLanguage = "en-US";

        var audioConfig = AudioConfig.FromStreamInput(audioStream);
        _transcriber = new ConversationTranscriber(speechConfig, audioConfig);

        _transcriber.Transcribed += async (s, e) =>
        {
            if (e.Result.Reason == ResultReason.RecognizedSpeech)
            {
                await _publisher.PublishTranscriptSegment(new TranscriptSegment
                {
                    MeetingId = meetingId,
                    SpeakerName = e.Result.SpeakerId ?? "Unknown",
                    Text = e.Result.Text,
                    StartTime = e.Result.OffsetInTicks / 10_000_000.0, // ticks to seconds
                    Duration = e.Result.Duration.TotalSeconds,
                    Confidence = /* extract from detailed results if available */,
                    IsFinal = true
                });
            }
        };

        await _transcriber.StartTranscribingAsync();
    }
}
```

### 8.6 `TranscriptPublisher.cs` — Publish to Service Bus

```csharp
// Publishes transcript segments and bot lifecycle events to Azure Service Bus.
// Python service (Service B) consumes these messages.

public class TranscriptPublisher
{
    private readonly ServiceBusSender _sender;

    public async Task PublishTranscriptSegment(TranscriptSegment segment)
    {
        var message = new ServiceBusMessage(JsonSerializer.Serialize(new
        {
            @event = "transcript_segment",
            meeting_id = segment.MeetingId,
            speaker_name = segment.SpeakerName,
            text = segment.Text,
            start_time = segment.StartTime,
            end_time = segment.StartTime + segment.Duration,
            confidence = segment.Confidence,
            is_final = segment.IsFinal,
            sequence_number = segment.SequenceNumber
        }));
        message.SessionId = segment.MeetingId; // ensures ordered processing per meeting
        await _sender.SendMessageAsync(message);
    }

    public async Task PublishEvent(string eventType, string meetingId, Dictionary<string, object> data)
    {
        // For meeting_joined, meeting_ended, participant_update, error events
    }
}
```

### 8.7 `CommandListener.cs` — Receive Commands from Python

```csharp
// Listens on the "bot-commands" Service Bus queue for commands from Python.
//
// Commands:
// - "join_meeting": triggers BotService to join a Teams meeting
// - "leave_meeting": triggers BotService to hang up a specific call
// - "status": responds with current bot status (active calls, health)

public class CommandListener : IHostedService
{
    private readonly ServiceBusProcessor _processor;
    private readonly BotService _botService;

    // On message received:
    // 1. Deserialize command
    // 2. Route to appropriate BotService method
    // 3. Complete the message on success, abandon on failure
}
```

### 8.8 Webhook Controller for Graph Callbacks

```csharp
// The Graph Communications SDK requires an HTTP endpoint for callbacks.
// When the bot joins a call, Teams sends state change notifications here.
//
// Route: POST /api/calls
//
// The SDK handles most routing internally via:
// _commsClient.ProcessNotification(request)
//
// You handle these through event subscriptions on the call object:
// - CallUpdated: call state changed (establishing → established → terminated)
// - ParticipantsUpdated: someone joined or left
// - MediaStateChanged: media stream started/stopped

[ApiController]
[Route("api/calls")]
public class CallbackController : ControllerBase
{
    [HttpPost]
    public async Task<IActionResult> HandleCallback()
    {
        // Forward to SDK for processing
        // SDK routes to the appropriate CallHandler methods
    }
}
```

---

## 9. Service B — Brain Implementation (Python)

### 9.1 Configuration (`app/config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App
    APP_NAME: str = "teams-meeting-assistant-brain"
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

    # Azure Service Bus (communication with Media Bot)
    SERVICE_BUS_CONNECTION_STRING: str
    SERVICE_BUS_COMMAND_QUEUE: str = "bot-commands"
    SERVICE_BUS_EVENT_QUEUE: str = "bot-events"

    # Azure AI Foundry
    AI_FOUNDRY_ENDPOINT: str  # https://<resource>.openai.azure.com/
    AI_FOUNDRY_API_KEY: str
    AI_FOUNDRY_DEPLOYMENT_NAME: str = "gpt-4o-mini"
    AI_FOUNDRY_DEPLOYMENT_NAME_COMPLEX: str = "gpt-4o"

    # Meeting Bot Behavior
    BOT_JOIN_BEFORE_MINUTES: int = 1
    NUDGE_CHECK_INTERVAL_MINUTES: int = 30
    NUDGE_ESCALATION_THRESHOLD: int = 2
    LONG_MEETING_THRESHOLD_MINUTES: int = 120

    # Redis (for task queue, optional)
    REDIS_URL: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"
```

### 9.2 Database Models (`app/models/`)

Use SQLAlchemy 2.0 async style. All models must have `id` (UUID primary key), `created_at`, `updated_at`.

#### `base.py`
```python
import uuid
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

#### `meeting.py`
```python
class Meeting(Base, TimestampMixin):
    __tablename__ = "meetings"

    teams_meeting_id: str           # from Graph API onlineMeetingId
    thread_id: str                  # Teams chat thread ID
    join_url: str                   # Teams meeting join URL
    subject: str
    organizer_id: str               # Azure AD user ID
    organizer_name: str
    organizer_email: str
    scheduled_start: datetime       # UTC
    scheduled_end: datetime         # UTC
    actual_start: datetime | None
    actual_end: datetime | None
    status: str                     # "scheduled", "joining", "in_progress", "processing", "completed", "failed", "cancelled"
    graph_call_id: str | None       # Graph call ID once joined
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

#### `transcript.py`
```python
class TranscriptSegment(Base, TimestampMixin):
    __tablename__ = "transcript_segments"

    meeting_id: UUID               # FK -> meetings.id
    speaker_name: str
    speaker_id: str | None
    text: str
    start_time: float              # seconds from meeting start
    end_time: float
    confidence: float | None       # 0.0 - 1.0
    sequence_number: int           # ordering
```

#### `summary.py`
```python
class MeetingSummary(Base, TimestampMixin):
    __tablename__ = "meeting_summaries"

    meeting_id: UUID               # FK -> meetings.id (one-to-one)
    summary_text: str              # 3-5 paragraph summary
    decisions: list[dict]          # JSON: [{"decision": "...", "context": "..."}]
    key_topics: list[dict]         # JSON: [{"topic": "...", "timestamp": "...", "detail": "..."}]
    unresolved_questions: list[str]
    model_used: str                # e.g. "gpt-4o-mini"
    processing_time_seconds: float
    delivered: bool = False
    delivered_at: datetime | None
```

#### `action_item.py`
```python
class ActionItem(Base, TimestampMixin):
    __tablename__ = "action_items"

    meeting_id: UUID               # FK -> meetings.id
    description: str
    assigned_to_name: str          # raw name from transcript
    assigned_to_user_id: str | None
    assigned_to_email: str | None
    deadline: datetime | None
    priority: str                  # "high", "medium", "low"
    status: str                    # "pending", "in_progress", "completed", "snoozed"
    nudge_count: int = 0
    last_nudged_at: datetime | None
    completed_at: datetime | None
    snoozed_until: datetime | None
    source_quote: str | None       # exact transcript quote
```

#### `subscription.py`
```python
class GraphSubscription(Base, TimestampMixin):
    __tablename__ = "graph_subscriptions"

    subscription_id: str
    user_id: str
    resource: str
    expiration: datetime
    status: str                    # "active", "expired", "failed"


class UserPreference(Base, TimestampMixin):
    __tablename__ = "user_preferences"

    user_id: str
    display_name: str
    email: str
    opted_in: bool = True
    summary_delivery: str = "chat"  # "chat", "email", "both"
    nudge_enabled: bool = True
```

### 9.3 Graph Client (`app/services/graph_client.py`)

Wrap all Microsoft Graph API calls. Use `httpx.AsyncClient`.

```python
class GraphClient:
    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, token_provider, http_client):
        self.token_provider = token_provider
        self.http = http_client

    # --- Calendar Subscriptions ---
    async def create_calendar_subscription(self, user_id: str, webhook_url: str) -> dict:
        """POST /subscriptions. Resource: /users/{user_id}/events. Max ~3 day expiry."""

    async def renew_subscription(self, subscription_id: str, new_expiration: datetime) -> dict:
        """PATCH /subscriptions/{id}"""

    # --- Calendar Events ---
    async def get_upcoming_events(self, user_id: str, hours_ahead: int = 24) -> list[dict]:
        """GET /users/{user_id}/calendarView. Filter: isOnlineMeeting eq true."""

    async def get_event(self, user_id: str, event_id: str) -> dict:
        """GET /users/{user_id}/events/{event_id}"""

    # --- Chat ---
    async def post_to_meeting_chat(self, thread_id: str, adaptive_card: dict) -> dict:
        """POST /chats/{threadId}/messages. Content type: application/vnd.microsoft.card.adaptive"""

    async def send_proactive_message(self, user_id: str, adaptive_card: dict) -> dict:
        """Send 1:1 message to user via Bot Framework / Graph."""

    # --- Users ---
    async def search_user(self, display_name: str) -> list[dict]:
        """GET /users?$filter=startswith(displayName, '{name}')"""

    async def get_user(self, user_id: str) -> dict:
        """GET /users/{user_id}"""
```

### 9.4 Bot Orchestrator (`app/services/bot_orchestrator.py`)

Sends commands to the C# Media Bot via Azure Service Bus.

```python
from azure.servicebus.aio import ServiceBusClient

class BotOrchestrator:
    """
    Sends commands to the C# Media Bot via Azure Service Bus.

    Methods:
    - join_meeting(meeting): Sends "join_meeting" command with join URL + metadata
    - leave_meeting(meeting): Sends "leave_meeting" command
    - get_status(meeting): Sends "status" command
    """

    def __init__(self, service_bus_client: ServiceBusClient, settings: Settings):
        self.sender = service_bus_client.get_queue_sender(settings.SERVICE_BUS_COMMAND_QUEUE)

    async def join_meeting(self, meeting: Meeting) -> None:
        message = ServiceBusMessage(json.dumps({
            "command": "join_meeting",
            "meeting_id": str(meeting.id),
            "join_url": meeting.join_url,
            "thread_id": meeting.thread_id,
            "organizer_name": meeting.organizer_name,
            "subject": meeting.subject,
        }))
        message.session_id = str(meeting.id)
        await self.sender.send_messages(message)
        # Update meeting status to "joining"
```

### 9.5 Transcript Consumer (`app/services/transcript_consumer.py`)

Listens on the Service Bus `bot-events` queue for transcript segments and lifecycle events from the Media Bot.

```python
class TranscriptConsumer:
    """
    Background task that continuously consumes messages from the "bot-events" Service Bus queue.

    Handles these event types:
    - "transcript_segment": Store in DB (TranscriptSegment table)
    - "meeting_joined": Update meeting status to "in_progress", set actual_start
    - "meeting_ended": Update meeting status to "processing", set actual_end,
                       TRIGGER post-meeting processing pipeline
    - "participant_update": Create/update MeetingParticipant record
    - "error": Log error, update meeting status if fatal

    On "meeting_ended":
    1. Mark meeting as "processing"
    2. Assemble full transcript from all TranscriptSegment rows for this meeting
    3. Call ai_processor.process_meeting(meeting, segments)
    4. Call delivery.deliver_summary(meeting, summary, action_items)
    5. Mark meeting as "completed"

    Run this as a background task in FastAPI's lifespan.
    """

    def __init__(self, service_bus_client, db, ai_processor, delivery, settings):
        self.receiver = service_bus_client.get_queue_receiver(settings.SERVICE_BUS_EVENT_QUEUE)
        # ...

    async def start(self):
        """Runs in a loop, receiving and processing messages."""
        async for message in self.receiver:
            event = json.loads(str(message))
            await self._handle_event(event)
            await self.receiver.complete_message(message)

    async def _handle_event(self, event: dict):
        event_type = event["event"]
        if event_type == "transcript_segment":
            await self._store_transcript_segment(event)
        elif event_type == "meeting_ended":
            await self._process_meeting_end(event)
        # ... etc
```

### 9.6 Calendar Watcher (`app/services/calendar_watcher.py`)

```python
class CalendarWatcher:
    """
    1. On startup: creates Graph subscriptions for all opted-in users
    2. Receives webhook callbacks when calendar events change
    3. Extracts Teams meeting join URL from events
    4. Schedules the Media Bot to join via BotOrchestrator

    Graph webhook validation:
    - On subscription creation, Graph sends GET with ?validationToken=xxx
    - MUST respond 200 with the token as plain text body
    - Handle this in the webhook route, not here

    Graph subscription expiry:
    - Calendar subscriptions expire after ~3 days
    - Run renew_subscriptions() every 12 hours via APScheduler
    """

    async def handle_webhook(self, payload: dict) -> None:
        """
        Process Graph change notification.
        1. Extract event ID
        2. Get full event details via Graph
        3. Check if Teams meeting (has joinWebUrl)
        4. Store meeting in DB
        5. Schedule bot join via APScheduler (BOT_JOIN_BEFORE_MINUTES before start)
        """

    async def schedule_bot_join(self, meeting: Meeting) -> None:
        """Add a one-time APScheduler job that calls bot_orchestrator.join_meeting(meeting)"""

    async def renew_subscriptions(self) -> None:
        """Periodic task: renew Graph subscriptions before they expire."""
```

### 9.7 AI Processor (`app/services/ai_processor.py`)

```python
from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential

class AIProcessor:
    """
    Sends complete meeting transcripts to Azure AI Foundry for extraction.

    Model selection:
    - Meetings < LONG_MEETING_THRESHOLD_MINUTES: use gpt-4o-mini (cheap, fast, 128K context)
    - Meetings >= threshold: use chunked processing with gpt-4o

    Extraction prompt requests JSON output with:
    - summary (3-5 paragraphs)
    - action_items[] (description, assigned_to, deadline, priority, source_quote)
    - decisions[] (decision, context)
    - key_topics[] (topic, timestamp, detail)
    - unresolved_questions[]

    For long meetings (>2 hours):
    1. Split transcript into 30-minute chunks
    2. Summarize each chunk independently
    3. Do a final "summary of summaries" pass
    4. Merge and deduplicate action items across chunks
    """

    EXTRACTION_SYSTEM_PROMPT = """You are a meeting analyst. You receive a meeting transcript and extract structured information.
Respond ONLY with valid JSON matching this schema:
{
    "summary": "3-5 paragraph summary covering all key points",
    "action_items": [
        {
            "description": "What needs to be done",
            "assigned_to": "Person's name as mentioned in transcript",
            "deadline": "ISO 8601 date if mentioned, null otherwise",
            "priority": "high | medium | low",
            "source_quote": "Exact quote from transcript"
        }
    ],
    "decisions": [
        {"decision": "What was decided", "context": "Why/how decided"}
    ],
    "key_topics": [
        {"topic": "Topic name", "timestamp": "Approx timestamp", "detail": "Brief description"}
    ],
    "unresolved_questions": ["Question raised but not resolved"]
}"""

    async def process_meeting(self, meeting, transcript_segments) -> dict:
        """Main entry point. Returns structured dict matching schema above."""

    def _format_transcript(self, segments) -> str:
        """Format as: [HH:MM:SS] Speaker Name: Text"""

    async def _process_chunked(self, meeting, segments) -> dict:
        """For long meetings: chunk → summarize each → merge."""
```

### 9.8 Owner Resolver (`app/services/owner_resolver.py`)

```python
class OwnerResolver:
    """
    Match names from AI output to real Azure AD users.

    Strategy:
    1. Exact match against meeting participant display names (case-insensitive)
    2. First-name match: "John" → "John Smith" if only one John in participants
    3. Graph API search: GET /users?$filter=startswith(displayName, 'name')
    4. Fuzzy match using rapidfuzz if above fail
    5. If no match: return (None, None) — UI handles unresolved owners

    Returns: (user_id, email) or (None, None)
    """
```

### 9.9 Delivery Service (`app/services/delivery.py`)

```python
class DeliveryService:
    """
    Posts Adaptive Cards to Teams.

    deliver_summary(meeting, summary, action_items):
    1. Load summary_card.json template
    2. Populate with meeting title, duration, summary, action items table, decisions
    3. Post to meeting chat via graph_client.post_to_meeting_chat(thread_id, card)
    4. Mark summary.delivered = True

    send_nudge(action_item):
    1. Load nudge_card.json template
    2. Populate with action item details
    3. Send 1:1 to assignee via graph_client.send_proactive_message()
    4. Increment nudge_count

    send_escalation(action_item, meeting):
    After NUDGE_ESCALATION_THRESHOLD missed nudges, notify meeting organizer.
    """
```

### 9.10 Nudge Scheduler (`app/services/nudge_scheduler.py`)

```python
class NudgeScheduler:
    """
    Runs every NUDGE_CHECK_INTERVAL_MINUTES via APScheduler.

    Query action items where:
    - status is "pending" or "in_progress"
    - AND deadline within 24 hours OR past deadline
    - AND last_nudged_at is NULL or > 4 hours ago (don't spam)
    - AND snoozed_until is NULL or < now

    For each:
    - If nudge_count >= threshold: escalate to organizer
    - Else: send nudge to assignee
    """
```

---

## 10. API Routes (Service B)

### Webhook Route (`app/routes/webhooks.py`)

```python
@router.post("/webhooks/graph")
async def graph_webhook(request: Request):
    """
    CRITICAL: Graph webhook validation flow:
    1. On subscription creation, Graph sends with ?validationToken=xxx
       → Respond 200 with the token as plain text
    2. On actual changes, POST with JSON payload
       → Process async (background task)
       → Respond 202 within 3 seconds
    """
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        return PlainTextResponse(content=validation_token, status_code=200)

    payload = await request.json()
    background_tasks.add_task(calendar_watcher.handle_webhook, payload)
    return Response(status_code=202)
```

### Meeting Routes (`app/routes/meetings.py`) — for the UI

```python
GET  /api/meetings                    # List meetings (filterable by status)
GET  /api/meetings/{id}               # Get meeting with summary + action items
GET  /api/meetings/{id}/transcript    # Get full transcript
POST /api/meetings/{id}/reprocess     # Re-run AI processing on existing transcript
```

### Action Item Routes (`app/routes/action_items.py`) — for the UI

```python
GET   /api/action-items               # List (filterable by status, user)
PATCH /api/action-items/{id}          # Update status/details
POST  /api/action-items/{id}/complete # Mark complete
POST  /api/action-items/{id}/snooze   # Snooze for N days
```

### Health Route

```python
GET /health                           # Returns {"status": "healthy"}
```

---

## 11. Adaptive Card Templates

### `templates/summary_card.json`

Adaptive Card (schema version 1.5 — Teams max) with:
- Header: meeting title, date/time, duration, participant count
- Collapsible summary section (`Action.ToggleVisibility`)
- Action items table using `ColumnSet` (Description, Owner, Deadline, Priority)
- Decisions bullet list
- Footer: "Powered by Meeting Assistant" + link to full transcript

### `templates/nudge_card.json`

- Header: "Action Item Reminder"
- Body: description, source meeting, deadline
- `Action.Submit` buttons with data payloads:
  - `{"action": "complete", "item_id": "..."}` — "Mark Complete"
  - `{"action": "snooze", "item_id": "...", "days": 1}` — "Snooze 1 Day"
  - `{"action": "update", "item_id": "..."}` — "Update Status"

### `templates/weekly_digest_card.json`

- All meetings from past week
- Open action items by assignee
- Completion rate stats

---

## 12. Main Application Entry Point (`app/main.py`)

```python
from fastapi import FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
    1. Initialize async DB engine + session factory
    2. Initialize service instances (GraphClient, BotOrchestrator, etc.)
    3. Start TranscriptConsumer as background task (asyncio.create_task)
    4. Start APScheduler with:
       a. Nudge scheduler: every NUDGE_CHECK_INTERVAL_MINUTES
       b. Subscription renewal: every 12 hours
    5. Call calendar_watcher.setup_subscriptions()

    Shutdown:
    1. Stop APScheduler
    2. Stop TranscriptConsumer
    3. Close Service Bus connections
    4. Close DB engine
    """
    yield

app = FastAPI(title="Teams Meeting Assistant Brain", version="1.0.0", lifespan=lifespan)

# Include routers
# /webhooks, /api/meetings, /api/action-items, /health
```

---

## 13. Deployment

### Service A — Media Bot (C#)

Deploy to **Azure VM Scale Set** with:
- Windows Server 2022 image
- D2s v3 size (~$150-200/mo)
- Public IP per instance
- NSG rules: allow TCP 8445–65535 (media), TCP 443 (HTTPS callbacks)
- SSL certificate bound to domain
- DNS CNAME pointing to load balancer

Use the Bicep/ARM templates in `deployment/vmss/`.

### Service B — Brain (Python)

#### `Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

Note: `--workers 1` because the Service Bus consumer needs to run as a single background task per process. Scale horizontally with Container Apps replicas if needed.

#### `docker-compose.yml` (local dev)
```yaml
version: "3.8"
services:
  brain:
    build: ./brain
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - postgres
      - redis

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

Deploy to **Azure Container Apps** (~$30-60/mo).

### Estimated Total Monthly Cost

| Resource | Cost |
|---------|------|
| VMSS (Windows, D2s v3) for Media Bot | ~$150–200 |
| Azure Container Apps for Brain | ~$30–60 |
| Azure AI Speech (transcription) | ~$1/hr of audio |
| Azure AI Foundry (GPT-4o-mini) | ~$0.01–0.05 per meeting |
| PostgreSQL Flexible Server | ~$25–50 |
| Azure Service Bus (Basic) | ~$0.05/mo |
| Azure Bot Service | Free tier |
| **Total (excl. transcription)** | **~$210–320/mo** |

At 100 hours of meetings/month: add ~$100 for Speech API = **~$310–420/mo total**.

---

## 14. Dependencies

### Service A — C# (`MediaBot.csproj`)

```xml
<PackageReference Include="Microsoft.Graph.Communications.Calls" Version="1.2.*" />
<PackageReference Include="Microsoft.Graph.Communications.Calls.Media" Version="1.2.*" />
<PackageReference Include="Microsoft.Graph.Communications.Common" Version="1.2.*" />
<PackageReference Include="Microsoft.Skype.Bots.Media" Version="1.2.*" />
<PackageReference Include="Microsoft.CognitiveServices.Speech" Version="1.42.*" />
<PackageReference Include="Azure.Messaging.ServiceBus" Version="7.18.*" />
<PackageReference Include="Microsoft.Identity.Client" Version="4.66.*" />
```

### Service B — Python (`requirements.txt`)

```
# Web Framework
fastapi==0.115.*
uvicorn[standard]==0.34.*

# Database
sqlalchemy[asyncio]==2.0.*
asyncpg==0.30.*
alembic==1.14.*

# Microsoft Auth
msal==1.31.*

# Azure Service Bus
azure-servicebus==7.12.*

# Azure AI Foundry
azure-ai-inference==1.0.*

# HTTP Client
httpx==0.28.*

# Scheduling
apscheduler==3.10.*

# Pydantic
pydantic==2.10.*
pydantic-settings==2.7.*

# Utilities
python-dotenv==1.0.*
rapidfuzz==3.10.*
tenacity==9.0.*
python-json-logger==3.2.*

# Redis (optional)
redis==5.2.*
```

### Dev dependencies (`requirements-dev.txt`)

```
-r requirements.txt
pytest==8.3.*
pytest-asyncio==0.24.*
httpx==0.28.*
factory-boy==3.3.*
faker==33.*
```

---

## 15. Development Order

Build and test in this exact sequence:

### Phase 1: Foundation
1. Service B project structure + `config.py`
2. Database models + Alembic setup + initial migration
3. `main.py` — bare FastAPI app with health route
4. `docker-compose.yml` — verify app + postgres start
5. `utils/auth.py` — MSAL token acquisition

### Phase 2: Calendar + Meeting Detection
6. `graph_client.py` — calendar subscription + event methods
7. `calendar_watcher.py` — subscription management + webhook handling
8. `routes/webhooks.py` — Graph webhook endpoint (with validation token handling)
9. Test: create subscription, receive webhook, meeting stored in DB

### Phase 3: Inter-Service Communication
10. Set up Azure Service Bus queues (bot-commands, bot-events)
11. `bot_orchestrator.py` — send commands to Service Bus
12. `transcript_consumer.py` — consume events from Service Bus, store in DB
13. Test with mock messages: simulate bot events, verify DB storage

### Phase 4: Media Bot (C#) — This is the hardest phase
14. Service A project structure + configuration
15. `BotService.cs` — Graph Communications SDK setup, bot registration
16. `CommandListener.cs` — receive commands from Service Bus
17. `CallHandler.cs` — join meeting, handle call state changes
18. `AudioFrameProcessor.cs` — receive raw audio frames
19. `SpeechTranscriber.cs` — Azure Speech integration
20. `TranscriptPublisher.cs` — publish transcripts to Service Bus
21. Webhook controller for Graph callbacks
22. Deploy to Azure (VMSS or Cloud Service)
23. **TEST: Bot joins a real Teams meeting, transcription flows to Python via Service Bus**

### Phase 5: AI Processing
24. `ai_processor.py` — prompt building + AI Foundry integration
25. `owner_resolver.py` — name resolution
26. Test: feed a transcript, get structured output

### Phase 6: Delivery + Nudges
27. Adaptive Card JSON templates
28. `delivery.py` — post cards to Teams chat
29. `nudge_scheduler.py` — periodic nudge logic
30. `routes/action_items.py` — CRUD for UI
31. `routes/meetings.py` — full CRUD for UI
32. Test: summary card appears in Teams after meeting ends

### Phase 7: Polish
33. Error handling + retry logic (Tenacity)
34. Structured logging
35. End-to-end test: meeting scheduled → bot joins → transcript → summary → nudge

---

## 16. Critical Gotchas

1. **Phase 4 (Media Bot) is the hardest part.** Most developers spend 60%+ of their time on Azure setup, permissions, certificates, and networking. Budget extra time. Start with Microsoft's `AudioVideoPlaybackBot` sample from `github.com/microsoftgraph/microsoft-graph-comms-samples` and modify it.

2. **NuGet SDK expiry** — `Microsoft.Graph.Communications.Calls.Media` and `Microsoft.Skype.Bots.Media` expire ~every 3 months. If you don't update, the bot silently stops receiving audio with no error message. Set a monthly reminder to check for updates.

3. **updateRecordingStatus is mandatory** — Before processing any audio, call `UpdateRecordingStatusAsync(RecordingStatus.Recording)`. This is a Microsoft compliance requirement. Failure to do this may result in your app being blocked by Microsoft.

4. **Graph webhook validation** — When creating a subscription, Graph sends a GET with `?validationToken=xxx`. You MUST echo it back as plain text 200 response. If you miss this, the subscription silently fails to create.

5. **Graph subscription expiry** — Calendar subscriptions expire after ~3 days. You MUST renew them proactively every 12 hours. If they expire, you stop getting notifications with no error.

6. **Media bot needs public IP** — Each bot instance needs a public IP with TCP 8445–65535 open. No way around this — real-time media requires direct connectivity.

7. **One call per VM instance** — Each real-time media call is pinned to the specific VM that accepted it. If that VM dies, the call drops. Plan for single-instance reliability per concurrent meeting.

8. **Bot may get stuck in lobby** — Configure Teams admin policy to auto-admit bots. Implement a 2-minute lobby timeout with retry in the bot.

9. **Permission errors 7503/7505** — These mean Graph permissions aren't set up correctly. Triple-check: all permissions added, admin consent granted, Application Access Policy allows the bot.

10. **Token caching** — MSAL handles token caching. Use the same `ConfidentialClientApplication` instance throughout the app lifecycle. Don't manually cache tokens.

11. **Adaptive Card schema version 1.5** — Teams supports up to 1.5. Don't use 1.6+ features.

12. **Service Bus message ordering** — Use `session_id = meeting_id` to ensure transcript segments for the same meeting are processed in order.

13. **Long meetings + LLM context** — GPT-4o-mini has 128K context. A 1-hour transcript is ~10-15K tokens. Only need chunking for 3+ hour meetings.

---

## 17. Environment Setup Checklist

Before writing any code, complete these:

- [ ] Azure subscription active
- [ ] Microsoft Entra ID app registration created
- [ ] Graph API permissions added (all 7 from Section 5)
- [ ] Admin consent granted by tenant admin
- [ ] Azure Bot Service created, linked to app registration, Teams channel enabled
- [ ] Calling enabled on Bot Service Teams channel (webhook URL set)
- [ ] Azure AI Speech resource created
- [ ] Azure AI Foundry resource with gpt-4o-mini deployment
- [ ] Azure Service Bus namespace + 2 queues (bot-commands, bot-events)
- [ ] PostgreSQL database provisioned (local Docker for dev)
- [ ] SSL certificate for media bot domain
- [ ] Public IP allocated for media bot
- [ ] DNS CNAME for media bot domain
- [ ] NSG rules: TCP 443 + 8445–65535
- [ ] `.env` file populated for Service B
- [ ] `appsettings.json` populated for Service A
- [ ] ngrok Pro account for local dev (needs TCP tunnel for media bot)
- [ ] Clone `microsoft-graph-comms-samples` for reference

---

## 18. Reference Samples & Docs

### Microsoft's Official Samples (start here for Service A)

| Sample | Use For | Location |
|--------|---------|----------|
| **AudioVideoPlaybackBot** | Join meetings, access media streams | `github.com/microsoftgraph/microsoft-graph-comms-samples` → `Samples/V1.0Samples/LocalMediaSamples/` |
| **PolicyRecordingBot** | Compliance recording, auto-join | Same repo |
| **EchoBot** | Simplest media bot: echo audio back | Same repo |

**Recommended:** Fork `AudioVideoPlaybackBot`. It already handles call join, media session setup, audio/video frame events, webhook handling, and Cloud Service deployment. Strip out the video/playback parts, add your transcription + Service Bus publishing.

### Key Documentation

- Register Calling Bot: `learn.microsoft.com/en-us/microsoftteams/platform/bots/calls-and-meetings/registering-calling-bot`
- Real-Time Media Concepts: `learn.microsoft.com/en-us/microsoftteams/platform/bots/calls-and-meetings/real-time-media-concepts`
- App-Hosted Media Bot Requirements: `learn.microsoft.com/en-us/microsoftteams/platform/bots/calls-and-meetings/requirements-considerations-application-hosted-media-bots`
- Graph Communications SDK: `microsoftgraph.github.io/microsoft-graph-comms-samples/docs/`
- Create Call API: `learn.microsoft.com/en-us/graph/api/application-post-calls`
- Azure AI Speech Real-Time: `learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-recognize-speech`
- Azure Service Bus Python SDK: `learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-python-how-to-use-queues`
