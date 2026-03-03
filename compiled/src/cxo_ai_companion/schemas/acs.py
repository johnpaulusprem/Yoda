"""Pydantic v2 schemas for ACS (Azure Communication Services) callback/event payloads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ACS Transcription schemas
# ---------------------------------------------------------------------------


class ACSTranscriptionWord(BaseModel):
    """Individual word within an ACS transcription result.

    Attributes:
        text: The transcribed word.
        offset: Start offset in 100-nanosecond ticks.
        duration: Duration in 100-nanosecond ticks.
    """

    text: str
    offset: int | None = None
    duration: int | None = None


class ACSTranscriptionData(BaseModel):
    """Payload for a single transcription result from ACS.

    Contains the transcribed text, timing information, word-level detail,
    and the participant who spoke.

    Attributes:
        text: Full transcribed text for this segment.
        format: Text format (``display`` or ``lexical``).
        confidence: Speech recognition confidence score (0.0--1.0).
        offset: Start offset in 100-nanosecond ticks.
        duration: Duration in 100-nanosecond ticks.
        words: Word-level transcription detail.
        participant_raw_id: ACS raw ID of the speaker.
        result_status: Whether this is a ``Final`` or ``Intermediate`` result.
    """

    text: str
    format: str | None = Field(default=None, description="display or lexical")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    offset: int = Field(default=0, description="Offset in 100-nanosecond ticks")
    duration: int = Field(default=0, description="Duration in 100-nanosecond ticks")
    words: list[ACSTranscriptionWord] = Field(default_factory=list)
    participant_raw_id: str | None = Field(
        default=None, alias="participantRawID"
    )
    result_status: str = Field(
        default="Final", alias="resultStatus"
    )  # Final | Intermediate

    model_config = {"populate_by_name": True}


class ACSTranscriptionMetadata(BaseModel):
    """Metadata message sent once when the ACS transcription WebSocket connects.

    Provides session identifiers and locale for the transcription stream.

    Attributes:
        call_connection_id: ACS call connection identifier.
        correlation_id: Correlation ID for distributed tracing.
        subscription_id: ACS subscription identifier.
        locale: Locale/language code for the transcription.
    """

    call_connection_id: str | None = Field(default=None, alias="callConnectionId")
    correlation_id: str | None = Field(default=None, alias="correlationId")
    subscription_id: str | None = Field(default=None, alias="subscriptionId")
    locale: str | None = None

    model_config = {"populate_by_name": True}


class ACSTranscriptionEvent(BaseModel):
    """Top-level envelope for any message arriving on the ACS transcription WebSocket.

    The ``kind`` field determines which nested payload is populated.

    Attributes:
        kind: Message type (TranscriptionData, TranscriptionMetadata, or WordData).
        transcription_data: Transcription result payload, if kind is TranscriptionData.
        transcription_metadata: Metadata payload, if kind is TranscriptionMetadata.
    """

    kind: str = Field(
        ...,
        description="TranscriptionData, TranscriptionMetadata, or WordData",
    )
    transcription_data: ACSTranscriptionData | None = Field(
        default=None, alias="transcriptionData"
    )
    transcription_metadata: ACSTranscriptionMetadata | None = Field(
        default=None, alias="transcriptionMetadata"
    )

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# ACS Media Streaming schemas
# ---------------------------------------------------------------------------


class ACSMediaStreamingData(BaseModel):
    """Payload for a media (audio) streaming chunk from ACS.

    Contains base64-encoded PCM audio data and speaker identification.

    Attributes:
        timestamp: Timestamp of the audio chunk.
        participant_raw_id: ACS raw ID of the speaker.
        data: Base64-encoded audio chunk (PCM 16-bit 16 kHz mono).
        is_silent: Whether this chunk contains silence.
    """

    timestamp: str | None = None
    participant_raw_id: str | None = Field(
        default=None, alias="participantRawID"
    )
    data: str | None = Field(
        default=None,
        description="Base64-encoded audio chunk (PCM 16-bit 16kHz mono)",
    )
    is_silent: bool = Field(default=False, alias="isSilent")

    model_config = {"populate_by_name": True}


class ACSMediaStreamingMetadata(BaseModel):
    """Metadata message sent once when the ACS media streaming WebSocket connects.

    Describes the audio format for subsequent streaming data messages.

    Attributes:
        call_connection_id: ACS call connection identifier.
        media_subscription_id: ACS media subscription identifier.
        encoding: Audio encoding format (e.g. PCM).
        sample_rate: Audio sample rate in Hz (e.g. 16000).
        channels: Number of audio channels (typically 1 for mono).
        length: Expected chunk length in bytes.
    """

    call_connection_id: str | None = Field(default=None, alias="callConnectionId")
    media_subscription_id: str | None = Field(
        default=None, alias="mediaSubscriptionId"
    )
    encoding: str | None = None
    sample_rate: int | None = Field(default=None, alias="sampleRate")
    channels: int | None = None
    length: int | None = None

    model_config = {"populate_by_name": True}


class ACSMediaStreamingMessage(BaseModel):
    """Top-level envelope for any message arriving on the ACS media streaming WebSocket.

    The ``kind`` field determines which nested payload is populated.

    Attributes:
        kind: Message type (AudioData or AudioMetadata).
        audio_data: Audio streaming data payload, if kind is AudioData.
        audio_metadata: Audio metadata payload, if kind is AudioMetadata.
    """

    kind: str = Field(..., description="AudioData or AudioMetadata")
    audio_data: ACSMediaStreamingData | None = Field(
        default=None, alias="audioData"
    )
    audio_metadata: ACSMediaStreamingMetadata | None = Field(
        default=None, alias="audioMetadata"
    )

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# ACS Call Automation callback event schemas (CloudEvents)
# ---------------------------------------------------------------------------


class ACSCallParticipant(BaseModel):
    """A single participant inside an ACS ParticipantsUpdated callback event.

    Attributes:
        raw_id: ACS raw identifier for the participant.
        display_name: Participant's display name.
        identifier: ACS communication identifier object.
        is_muted: Whether the participant is currently muted.
    """

    raw_id: str | None = Field(default=None, alias="rawId")
    display_name: str | None = Field(default=None, alias="displayName")
    identifier: dict | None = None
    is_muted: bool | None = Field(default=None, alias="isMuted")


class ACSCallEventData(BaseModel):
    """The ``data`` portion of a CloudEvent for ACS Call Automation callbacks.

    Contains call identifiers, operation context, and optional participant
    list for ParticipantsUpdated events.

    Attributes:
        call_connection_id: ACS call connection identifier.
        server_call_id: Server-side call identifier.
        correlation_id: Correlation ID for distributed tracing.
        operation_context: Caller-supplied context from the originating API call.
        result_information: Operation result details (code, subcode, message).
        participants: List of participants, present in ParticipantsUpdated events.
    """

    call_connection_id: str | None = Field(default=None, alias="callConnectionId")
    server_call_id: str | None = Field(default=None, alias="serverCallId")
    correlation_id: str | None = Field(default=None, alias="correlationId")
    operation_context: str | None = Field(default=None, alias="operationContext")
    result_information: dict | None = Field(default=None, alias="resultInformation")
    participants: list[ACSCallParticipant] | None = None

    model_config = {"populate_by_name": True}


class ACSCallbackEvent(BaseModel):
    """A single CloudEvent as sent by ACS Call Automation callbacks.

    ACS posts an array of these to the callback URL. Example event types
    include CallConnected, CallDisconnected, ParticipantsUpdated,
    TranscriptionStarted, and TranscriptionStopped.

    Attributes:
        id: CloudEvent unique identifier.
        source: CloudEvent source URI.
        type: Full CloudEvent type (e.g. ``Microsoft.Communication.CallConnected``).
        subject: CloudEvent subject, typically the call resource path.
        time: Timestamp when the event occurred.
        data: Nested event data containing call and participant details.
        specversion: CloudEvents specification version (defaults to ``1.0``).
    """

    id: str | None = None
    source: str | None = None
    type: str = Field(
        ...,
        description="CloudEvent type, e.g. 'Microsoft.Communication.CallConnected'",
    )
    subject: str | None = None
    time: datetime | None = None
    data: ACSCallEventData = Field(default_factory=ACSCallEventData)
    specversion: str | None = Field(default="1.0")

    model_config = {"populate_by_name": True}

    @property
    def event_name(self) -> str:
        """Extract the short event name from the full CloudEvent type."""
        parts = self.type.rsplit(".", 1)
        return parts[-1] if len(parts) > 1 else self.type

    @property
    def call_connection_id(self) -> str | None:
        """Convenience accessor for the call connection ID buried in data."""
        return self.data.call_connection_id


class ACSCallConnectedEvent(BaseModel):
    """Typed schema for a CallConnected event payload.

    Received when the bot successfully joins an ACS call.

    Attributes:
        call_connection_id: ACS call connection identifier.
        server_call_id: Server-side call identifier.
        correlation_id: Correlation ID for distributed tracing.
    """

    call_connection_id: str = Field(alias="callConnectionId")
    server_call_id: str = Field(alias="serverCallId")
    correlation_id: str | None = Field(default=None, alias="correlationId")

    model_config = {"populate_by_name": True}


class ACSCallDisconnectedEvent(BaseModel):
    """Typed schema for a CallDisconnected event payload.

    Received when the bot or call is disconnected from an ACS call.

    Attributes:
        call_connection_id: ACS call connection identifier.
        server_call_id: Server-side call identifier.
        correlation_id: Correlation ID for distributed tracing.
    """

    call_connection_id: str = Field(alias="callConnectionId")
    server_call_id: str = Field(alias="serverCallId")
    correlation_id: str | None = Field(default=None, alias="correlationId")

    model_config = {"populate_by_name": True}
