"""Pydantic schemas for ACS callback/event payloads."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ACS Transcription schemas
# ---------------------------------------------------------------------------

class ACSTranscriptionWord(BaseModel):
    """Individual word within a transcription result."""
    text: str
    offset: int | None = None
    duration: int | None = None


class ACSTranscriptionData(BaseModel):
    """Payload for a single transcription result from ACS.

    ACS sends these inside a ``TranscriptionData`` message:
    {
        "kind": "TranscriptionData",
        "transcriptionData": { ... this model ... }
    }
    """
    text: str
    format: str | None = Field(default=None, description="display or lexical")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    offset: int = Field(default=0, description="Offset in 100-nanosecond ticks from start")
    duration: int = Field(default=0, description="Duration in 100-nanosecond ticks")
    words: list[ACSTranscriptionWord] = Field(default_factory=list)
    participant_raw_id: str | None = Field(
        default=None,
        alias="participantRawID",
        description="ACS raw ID of the speaker, e.g. 8:acs:...",
    )
    result_status: str = Field(
        default="Final",
        alias="resultStatus",
        description="'Final' or 'Intermediate'",
    )

    model_config = {"populate_by_name": True}


class ACSTranscriptionMetadata(BaseModel):
    """Metadata message sent once when the transcription WebSocket connects."""
    call_connection_id: str | None = Field(default=None, alias="callConnectionId")
    correlation_id: str | None = Field(default=None, alias="correlationId")
    subscription_id: str | None = Field(default=None, alias="subscriptionId")
    locale: str | None = None

    model_config = {"populate_by_name": True}


class ACSTranscriptionMessage(BaseModel):
    """Top-level envelope for any message arriving on the transcription WebSocket."""
    kind: str = Field(
        ...,
        description="'TranscriptionData', 'TranscriptionMetadata', or 'WordData'",
    )
    transcription_data: ACSTranscriptionData | None = Field(
        default=None,
        alias="transcriptionData",
    )
    transcription_metadata: ACSTranscriptionMetadata | None = Field(
        default=None,
        alias="transcriptionMetadata",
    )

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# ACS Media Streaming schemas
# ---------------------------------------------------------------------------

class ACSMediaStreamingData(BaseModel):
    """Payload for a media (audio) streaming chunk from ACS.

    Typically raw audio bytes encoded as base64, but we parse the JSON
    envelope here.  Audio content itself is handled in the media streaming
    WebSocket handler.
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
    """Metadata message sent once when the media streaming WebSocket connects."""
    call_connection_id: str | None = Field(default=None, alias="callConnectionId")
    media_subscription_id: str | None = Field(default=None, alias="mediaSubscriptionId")
    encoding: str | None = None
    sample_rate: int | None = Field(default=None, alias="sampleRate")
    channels: int | None = None
    length: int | None = None

    model_config = {"populate_by_name": True}


class ACSMediaStreamingMessage(BaseModel):
    """Top-level envelope for any message arriving on the media streaming WebSocket."""
    kind: str = Field(
        ...,
        description="'AudioData' or 'AudioMetadata'",
    )
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
    """Represents a single participant inside a ParticipantsUpdated event."""
    raw_id: str | None = Field(default=None, alias="rawId")
    display_name: str | None = Field(default=None, alias="displayName")
    identifier: dict | None = None
    is_muted: bool | None = Field(default=None, alias="isMuted")


class ACSCallEventData(BaseModel):
    """The ``data`` portion of a CloudEvent for ACS Call Automation.

    Different event types populate different subsets of these fields.
    """
    call_connection_id: str | None = Field(default=None, alias="callConnectionId")
    server_call_id: str | None = Field(default=None, alias="serverCallId")
    correlation_id: str | None = Field(default=None, alias="correlationId")
    operation_context: str | None = Field(default=None, alias="operationContext")
    result_information: dict | None = Field(default=None, alias="resultInformation")
    participants: list[ACSCallParticipant] | None = None

    model_config = {"populate_by_name": True}


class ACSCallEvent(BaseModel):
    """A single CloudEvent as sent by ACS Call Automation callbacks.

    ACS posts an array of these to the callback URL.
    Example event types:
        - Microsoft.Communication.CallConnected
        - Microsoft.Communication.CallDisconnected
        - Microsoft.Communication.ParticipantsUpdated
        - Microsoft.Communication.TranscriptionStarted
        - Microsoft.Communication.TranscriptionStopped
        - Microsoft.Communication.MediaStreamingStarted
        - Microsoft.Communication.MediaStreamingStopped
        - Microsoft.Communication.PlayCompleted
        - Microsoft.Communication.PlayFailed
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
        """Extract the short event name from the full CloudEvent type.

        E.g. 'Microsoft.Communication.CallConnected' -> 'CallConnected'
        """
        parts = self.type.rsplit(".", 1)
        return parts[-1] if len(parts) > 1 else self.type

    @property
    def call_connection_id(self) -> str | None:
        """Convenience accessor for the call connection ID buried in data."""
        return self.data.call_connection_id
