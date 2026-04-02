"""
Event schema definitions for the Agentic AI Component Library.

This module provides comprehensive event schemas for all components
in the agentic AI system including agents, tools, LLMs, RAG pipelines,
security events, and system events.

Example:
    ```python
    from yoda_foundation.events.schemas.event_schemas import (
        BaseEvent,
        AgentEvent,
        ToolEvent,
        LLMEvent,
        RAGEvent,
        SecurityEvent,
        SystemEvent,
        EventSeverity,
        AgentEventType,
        ToolEventType,
    )

    # Create an agent event
    event = AgentEvent.create(
        event_type=AgentEventType.STARTED,
        agent_id="agent_001",
        agent_name="ResearchAgent",
        payload={"goal": "Analyze market trends"},
    )

    # Create an LLM event with token usage
    llm_event = LLMEvent.create(
        event_type=LLMEventType.RESPONSE,
        model="gpt-4",
        input_tokens=500,
        output_tokens=200,
        latency_ms=1500,
    )

    # Serialize for transmission
    event_dict = event.to_dict()
    ```
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class EventSeverity(Enum):
    """
    Severity level for events.

    Used to categorize events by importance and urgency.

    Attributes:
        DEBUG: Detailed debugging information
        INFO: General informational events
        WARNING: Warning conditions
        ERROR: Error conditions
        CRITICAL: Critical conditions requiring immediate attention

    Example:
        ```python
        if event.severity == EventSeverity.CRITICAL:
            await send_alert(event)
        elif event.severity == EventSeverity.ERROR:
            logger.error(f"Error event: {event.event_id}")
        ```
    """

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def numeric_value(self) -> int:
        """Get numeric severity value for comparison."""
        return {
            "debug": 0,
            "info": 1,
            "warning": 2,
            "error": 3,
            "critical": 4,
        }[self.value]

    def __lt__(self, other: EventSeverity) -> bool:
        return self.numeric_value < other.numeric_value

    def __le__(self, other: EventSeverity) -> bool:
        return self.numeric_value <= other.numeric_value

    def __gt__(self, other: EventSeverity) -> bool:
        return self.numeric_value > other.numeric_value

    def __ge__(self, other: EventSeverity) -> bool:
        return self.numeric_value >= other.numeric_value


# =============================================================================
# Agent Event Types
# =============================================================================


class AgentEventType(Enum):
    """
    Event types for agent-related events.

    Covers the full lifecycle and operations of agents.

    Example:
        ```python
        if event.event_type == AgentEventType.ERROR:
            await handle_agent_error(event)
        ```
    """

    STARTED = "agent.started"
    STOPPED = "agent.stopped"
    ERROR = "agent.error"
    DECISION = "agent.decision"
    THINKING = "agent.thinking"
    ACTION = "agent.action"
    ITERATION = "agent.iteration"
    GOAL_SET = "agent.goal_set"
    GOAL_COMPLETED = "agent.goal_completed"
    STATE_CHANGED = "agent.state_changed"
    DELEGATED = "agent.delegated"
    RECEIVED = "agent.received"


# =============================================================================
# Tool Event Types
# =============================================================================


class ToolEventType(Enum):
    """
    Event types for tool-related events.

    Covers tool invocation, results, and errors.

    Example:
        ```python
        if event.event_type == ToolEventType.INVOCATION:
            logger.info(f"Tool {event.tool_name} invoked")
        ```
    """

    INVOCATION = "tool.invocation"
    RESULT = "tool.result"
    ERROR = "tool.error"
    TIMEOUT = "tool.timeout"
    VALIDATION = "tool.validation"
    RETRY = "tool.retry"
    REGISTERED = "tool.registered"
    UNREGISTERED = "tool.unregistered"


# =============================================================================
# LLM Event Types
# =============================================================================


class LLMEventType(Enum):
    """
    Event types for LLM-related events.

    Covers LLM requests, responses, and token usage tracking.

    Example:
        ```python
        if event.event_type == LLMEventType.TOKEN_USAGE:
            await track_token_usage(event.tokens)
        ```
    """

    REQUEST = "llm.request"
    RESPONSE = "llm.response"
    TOKEN_USAGE = "llm.token_usage"
    STREAM_START = "llm.stream_start"
    STREAM_CHUNK = "llm.stream_chunk"
    STREAM_END = "llm.stream_end"
    ERROR = "llm.error"
    RATE_LIMITED = "llm.rate_limited"
    FALLBACK = "llm.fallback"


# =============================================================================
# RAG Event Types
# =============================================================================


class RAGEventType(Enum):
    """
    Event types for RAG pipeline events.

    Covers retrieval, embedding, reranking, and generation.

    Example:
        ```python
        if event.event_type == RAGEventType.RETRIEVAL:
            logger.info(f"Retrieved {event.document_count} documents")
        ```
    """

    RETRIEVAL = "rag.retrieval"
    EMBEDDING = "rag.embedding"
    RERANK = "rag.rerank"
    GENERATION = "rag.generation"
    CHUNK = "rag.chunk"
    STORE = "rag.store"
    QUERY = "rag.query"
    ERROR = "rag.error"


# =============================================================================
# Security Event Types
# =============================================================================


class SecurityEventType(Enum):
    """
    Event types for security-related events.

    Covers authentication, authorization, and security violations.

    Example:
        ```python
        if event.event_type == SecurityEventType.VIOLATION:
            await trigger_security_alert(event)
        ```
    """

    AUTH_ATTEMPT = "security.auth_attempt"
    AUTH_SUCCESS = "security.auth_success"
    AUTH_FAILURE = "security.auth_failure"
    ACCESS_GRANTED = "security.access_granted"
    ACCESS_DENIED = "security.access_denied"
    VIOLATION = "security.violation"
    PERMISSION_CHECK = "security.permission_check"
    TOKEN_ISSUED = "security.token_issued"
    TOKEN_REVOKED = "security.token_revoked"
    SESSION_CREATED = "security.session_created"
    SESSION_EXPIRED = "security.session_expired"
    AUDIT = "security.audit"


# =============================================================================
# System Event Types
# =============================================================================


class SystemEventType(Enum):
    """
    Event types for system-level events.

    Covers system startup, shutdown, health checks, and configuration.

    Example:
        ```python
        if event.event_type == SystemEventType.HEALTH_CHECK:
            await update_health_status(event)
        ```
    """

    STARTUP = "system.startup"
    SHUTDOWN = "system.shutdown"
    HEALTH_CHECK = "system.health_check"
    CONFIG_CHANGE = "system.config_change"
    RESOURCE_LIMIT = "system.resource_limit"
    MAINTENANCE = "system.maintenance"
    ERROR = "system.error"
    WARNING = "system.warning"


# =============================================================================
# Base Event
# =============================================================================


@dataclass
class BaseEvent:
    """
    Base event class for all events in the system.

    Provides common attributes for event identification, tracing,
    and serialization.

    Attributes:
        event_id: Unique identifier for this event
        timestamp: When the event was created
        source: Source component/service name
        event_type: Type of the event
        severity: Event severity level
        correlation_id: ID for tracing related events
        metadata: Additional event metadata
        tags: Tags for filtering and categorization

    Example:
        ```python
        event = BaseEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            source="agent_service",
            event_type="custom.event",
            severity=EventSeverity.INFO,
            metadata={"key": "value"},
        )

        # Serialize
        event_dict = event.to_dict()

        # Deserialize
        restored = BaseEvent.from_dict(event_dict)
        ```
    """

    event_id: str
    timestamp: datetime
    source: str
    event_type: str
    severity: EventSeverity = EventSeverity.INFO
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate and normalize event data."""
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=UTC)

    @classmethod
    def create(
        cls,
        event_type: str,
        source: str,
        severity: EventSeverity = EventSeverity.INFO,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> BaseEvent:
        """
        Factory method to create a base event.

        Args:
            event_type: Type of the event
            source: Source component name
            severity: Event severity level
            correlation_id: Correlation ID for tracing
            metadata: Additional metadata
            tags: Event tags

        Returns:
            New BaseEvent instance

        Example:
            ```python
            event = BaseEvent.create(
                event_type="custom.event",
                source="my_service",
                severity=EventSeverity.INFO,
                metadata={"action": "process"},
            )
            ```
        """
        return cls(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC),
            source=source,
            event_type=event_type,
            severity=severity,
            correlation_id=correlation_id or str(uuid.uuid4())[:12],
            metadata=metadata or {},
            tags=tags or [],
        )

    @property
    def age_seconds(self) -> float:
        """Get age of event in seconds."""
        return (datetime.now(UTC) - self.timestamp).total_seconds()

    def with_metadata(self, **kwargs: Any) -> BaseEvent:
        """
        Create a copy with additional metadata.

        Args:
            **kwargs: Metadata key-value pairs to add

        Returns:
            New BaseEvent with merged metadata
        """
        return BaseEvent(
            event_id=self.event_id,
            timestamp=self.timestamp,
            source=self.source,
            event_type=self.event_type,
            severity=self.severity,
            correlation_id=self.correlation_id,
            metadata={**self.metadata, **kwargs},
            tags=self.tags.copy(),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert event to dictionary for serialization.

        Returns:
            Dictionary representation of the event

        Example:
            ```python
            event_dict = event.to_dict()
            json_str = json.dumps(event_dict)
            ```
        """
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "event_type": self.event_type,
            "severity": self.severity.value,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseEvent:
        """
        Create event from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            BaseEvent instance

        Example:
            ```python
            data = json.loads(json_str)
            event = BaseEvent.from_dict(data)
            ```
        """
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        else:
            timestamp = datetime.now(UTC)

        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            timestamp=timestamp,
            source=data["source"],
            event_type=data["event_type"],
            severity=EventSeverity(data.get("severity", "info")),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
        )

    def __str__(self) -> str:
        """Human-readable string representation."""
        return f"Event({self.event_type}, id={self.event_id[:8]})"


# =============================================================================
# Agent Event
# =============================================================================


@dataclass
class AgentEvent(BaseEvent):
    """
    Event for agent-related activities.

    Captures agent lifecycle, decisions, and errors.

    Attributes:
        agent_id: Unique identifier of the agent
        agent_name: Human-readable agent name
        agent_event_type: Specific agent event type
        iteration: Current iteration number (if applicable)
        goal: Current agent goal
        state: Current agent state
        payload: Event-specific data

    Example:
        ```python
        # Agent started event
        event = AgentEvent.create(
            event_type=AgentEventType.STARTED,
            agent_id="agent_001",
            agent_name="ResearchAgent",
            goal="Analyze market data",
        )

        # Agent decision event
        decision_event = AgentEvent.create(
            event_type=AgentEventType.DECISION,
            agent_id="agent_001",
            agent_name="ResearchAgent",
            payload={
                "action": "search",
                "reasoning": "Need more data",
            },
        )

        # Agent error event
        error_event = AgentEvent.create(
            event_type=AgentEventType.ERROR,
            agent_id="agent_001",
            agent_name="ResearchAgent",
            severity=EventSeverity.ERROR,
            payload={
                "error": "Tool execution failed",
                "tool_name": "web_search",
            },
        )
        ```
    """

    agent_id: str = ""
    agent_name: str = ""
    agent_event_type: AgentEventType | None = None
    iteration: int | None = None
    goal: str | None = None
    state: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        event_type: AgentEventType,
        agent_id: str,
        agent_name: str = "",
        severity: EventSeverity = EventSeverity.INFO,
        correlation_id: str | None = None,
        iteration: int | None = None,
        goal: str | None = None,
        state: str | None = None,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> AgentEvent:
        """
        Factory method to create an agent event.

        Args:
            event_type: Type of agent event
            agent_id: Agent identifier
            agent_name: Agent name
            severity: Event severity
            correlation_id: Correlation ID for tracing
            iteration: Current iteration number
            goal: Current goal
            state: Current state
            payload: Event-specific data
            metadata: Additional metadata
            tags: Event tags

        Returns:
            New AgentEvent instance
        """
        # Auto-set severity for error events
        if event_type == AgentEventType.ERROR and severity == EventSeverity.INFO:
            severity = EventSeverity.ERROR

        return cls(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC),
            source=f"agent:{agent_id}",
            event_type=event_type.value,
            severity=severity,
            correlation_id=correlation_id or str(uuid.uuid4())[:12],
            metadata=metadata or {},
            tags=tags or ["agent"],
            agent_id=agent_id,
            agent_name=agent_name,
            agent_event_type=event_type,
            iteration=iteration,
            goal=goal,
            state=state,
            payload=payload or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        base_dict = super().to_dict()
        base_dict.update(
            {
                "agent_id": self.agent_id,
                "agent_name": self.agent_name,
                "agent_event_type": (
                    self.agent_event_type.value if self.agent_event_type else None
                ),
                "iteration": self.iteration,
                "goal": self.goal,
                "state": self.state,
                "payload": self.payload,
            }
        )
        return base_dict

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentEvent:
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        else:
            timestamp = datetime.now(UTC)

        agent_event_type = data.get("agent_event_type")
        if agent_event_type:
            agent_event_type = AgentEventType(agent_event_type)

        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            timestamp=timestamp,
            source=data["source"],
            event_type=data["event_type"],
            severity=EventSeverity(data.get("severity", "info")),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            agent_id=data.get("agent_id", ""),
            agent_name=data.get("agent_name", ""),
            agent_event_type=agent_event_type,
            iteration=data.get("iteration"),
            goal=data.get("goal"),
            state=data.get("state"),
            payload=data.get("payload", {}),
        )


# =============================================================================
# Tool Event
# =============================================================================


@dataclass
class ToolEvent(BaseEvent):
    """
    Event for tool-related activities.

    Captures tool invocations, results, and errors.

    Attributes:
        tool_name: Name of the tool
        tool_event_type: Specific tool event type
        agent_id: Agent that invoked the tool
        invocation_id: Unique invocation identifier
        input_params: Tool input parameters
        output: Tool output (for result events)
        error_message: Error message (for error events)
        duration_ms: Execution duration in milliseconds

    Example:
        ```python
        # Tool invocation event
        event = ToolEvent.create(
            event_type=ToolEventType.INVOCATION,
            tool_name="web_search",
            agent_id="agent_001",
            input_params={"query": "AI news"},
        )

        # Tool result event
        result_event = ToolEvent.create(
            event_type=ToolEventType.RESULT,
            tool_name="web_search",
            agent_id="agent_001",
            output={"results": [...]},
            duration_ms=1500,
        )

        # Tool error event
        error_event = ToolEvent.create(
            event_type=ToolEventType.ERROR,
            tool_name="web_search",
            agent_id="agent_001",
            error_message="Connection timeout",
            duration_ms=30000,
        )
        ```
    """

    tool_name: str = ""
    tool_event_type: ToolEventType | None = None
    agent_id: str | None = None
    invocation_id: str | None = None
    input_params: dict[str, Any] = field(default_factory=dict)
    output: Any | None = None
    error_message: str | None = None
    duration_ms: float | None = None

    @classmethod
    def create(
        cls,
        event_type: ToolEventType,
        tool_name: str,
        agent_id: str | None = None,
        invocation_id: str | None = None,
        input_params: dict[str, Any] | None = None,
        output: Any | None = None,
        error_message: str | None = None,
        duration_ms: float | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> ToolEvent:
        """
        Factory method to create a tool event.

        Args:
            event_type: Type of tool event
            tool_name: Name of the tool
            agent_id: Agent identifier
            invocation_id: Invocation identifier
            input_params: Tool input parameters
            output: Tool output
            error_message: Error message
            duration_ms: Execution duration
            severity: Event severity
            correlation_id: Correlation ID
            metadata: Additional metadata
            tags: Event tags

        Returns:
            New ToolEvent instance
        """
        # Auto-set severity for error events
        if event_type == ToolEventType.ERROR and severity == EventSeverity.INFO:
            severity = EventSeverity.ERROR

        return cls(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC),
            source=f"tool:{tool_name}",
            event_type=event_type.value,
            severity=severity,
            correlation_id=correlation_id or str(uuid.uuid4())[:12],
            metadata=metadata or {},
            tags=tags or ["tool"],
            tool_name=tool_name,
            tool_event_type=event_type,
            agent_id=agent_id,
            invocation_id=invocation_id or str(uuid.uuid4()),
            input_params=input_params or {},
            output=output,
            error_message=error_message,
            duration_ms=duration_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        base_dict = super().to_dict()
        base_dict.update(
            {
                "tool_name": self.tool_name,
                "tool_event_type": (self.tool_event_type.value if self.tool_event_type else None),
                "agent_id": self.agent_id,
                "invocation_id": self.invocation_id,
                "input_params": self.input_params,
                "output": self.output,
                "error_message": self.error_message,
                "duration_ms": self.duration_ms,
            }
        )
        return base_dict

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolEvent:
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        else:
            timestamp = datetime.now(UTC)

        tool_event_type = data.get("tool_event_type")
        if tool_event_type:
            tool_event_type = ToolEventType(tool_event_type)

        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            timestamp=timestamp,
            source=data["source"],
            event_type=data["event_type"],
            severity=EventSeverity(data.get("severity", "info")),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            tool_name=data.get("tool_name", ""),
            tool_event_type=tool_event_type,
            agent_id=data.get("agent_id"),
            invocation_id=data.get("invocation_id"),
            input_params=data.get("input_params", {}),
            output=data.get("output"),
            error_message=data.get("error_message"),
            duration_ms=data.get("duration_ms"),
        )


# =============================================================================
# LLM Event
# =============================================================================


@dataclass
class LLMEvent(BaseEvent):
    """
    Event for LLM-related activities.

    Captures LLM requests, responses, and token usage.

    Attributes:
        model: Model identifier
        llm_event_type: Specific LLM event type
        provider: LLM provider name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        total_tokens: Total token count
        latency_ms: Request latency in milliseconds
        prompt_hash: Hash of the prompt (for deduplication)
        temperature: Temperature setting
        max_tokens: Max tokens setting
        error_message: Error message (for error events)

    Example:
        ```python
        # LLM request event
        event = LLMEvent.create(
            event_type=LLMEventType.REQUEST,
            model="gpt-4",
            provider="openai",
            input_tokens=500,
        )

        # LLM response event
        response_event = LLMEvent.create(
            event_type=LLMEventType.RESPONSE,
            model="gpt-4",
            provider="openai",
            input_tokens=500,
            output_tokens=200,
            latency_ms=1500,
        )

        # Token usage event
        usage_event = LLMEvent.create(
            event_type=LLMEventType.TOKEN_USAGE,
            model="gpt-4",
            provider="openai",
            input_tokens=500,
            output_tokens=200,
            total_tokens=700,
        )
        ```
    """

    model: str = ""
    llm_event_type: LLMEventType | None = None
    provider: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float | None = None
    prompt_hash: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    error_message: str | None = None

    @classmethod
    def create(
        cls,
        event_type: LLMEventType,
        model: str,
        provider: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: float | None = None,
        prompt_hash: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        error_message: str | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> LLMEvent:
        """
        Factory method to create an LLM event.

        Args:
            event_type: Type of LLM event
            model: Model identifier
            provider: LLM provider
            input_tokens: Input token count
            output_tokens: Output token count
            total_tokens: Total token count
            latency_ms: Request latency
            prompt_hash: Prompt hash
            temperature: Temperature setting
            max_tokens: Max tokens setting
            error_message: Error message
            severity: Event severity
            correlation_id: Correlation ID
            metadata: Additional metadata
            tags: Event tags

        Returns:
            New LLMEvent instance
        """
        # Calculate total if not provided
        if total_tokens is None and input_tokens and output_tokens:
            total_tokens = input_tokens + output_tokens

        # Auto-set severity for error events
        if event_type == LLMEventType.ERROR and severity == EventSeverity.INFO:
            severity = EventSeverity.ERROR

        return cls(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC),
            source=f"llm:{model}",
            event_type=event_type.value,
            severity=severity,
            correlation_id=correlation_id or str(uuid.uuid4())[:12],
            metadata=metadata or {},
            tags=tags or ["llm"],
            model=model,
            llm_event_type=event_type,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            prompt_hash=prompt_hash,
            temperature=temperature,
            max_tokens=max_tokens,
            error_message=error_message,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        base_dict = super().to_dict()
        base_dict.update(
            {
                "model": self.model,
                "llm_event_type": (self.llm_event_type.value if self.llm_event_type else None),
                "provider": self.provider,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "latency_ms": self.latency_ms,
                "prompt_hash": self.prompt_hash,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "error_message": self.error_message,
            }
        )
        return base_dict

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMEvent:
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        else:
            timestamp = datetime.now(UTC)

        llm_event_type = data.get("llm_event_type")
        if llm_event_type:
            llm_event_type = LLMEventType(llm_event_type)

        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            timestamp=timestamp,
            source=data["source"],
            event_type=data["event_type"],
            severity=EventSeverity(data.get("severity", "info")),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            model=data.get("model", ""),
            llm_event_type=llm_event_type,
            provider=data.get("provider", ""),
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
            total_tokens=data.get("total_tokens"),
            latency_ms=data.get("latency_ms"),
            prompt_hash=data.get("prompt_hash"),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
            error_message=data.get("error_message"),
        )


# =============================================================================
# RAG Event
# =============================================================================


@dataclass
class RAGEvent(BaseEvent):
    """
    Event for RAG pipeline activities.

    Captures retrieval, embedding, reranking, and generation events.

    Attributes:
        rag_event_type: Specific RAG event type
        query: Query text
        document_count: Number of documents
        chunk_count: Number of chunks
        embedding_model: Embedding model used
        reranker_model: Reranker model used
        top_k: Number of results requested
        similarity_scores: Retrieved document scores
        latency_ms: Operation latency
        collection_name: Vector store collection

    Example:
        ```python
        # Retrieval event
        event = RAGEvent.create(
            event_type=RAGEventType.RETRIEVAL,
            query="What is machine learning?",
            document_count=10,
            top_k=10,
            latency_ms=50,
        )

        # Embedding event
        embed_event = RAGEvent.create(
            event_type=RAGEventType.EMBEDDING,
            embedding_model="text-embedding-3-small",
            chunk_count=100,
            latency_ms=200,
        )

        # Rerank event
        rerank_event = RAGEvent.create(
            event_type=RAGEventType.RERANK,
            reranker_model="cross-encoder",
            document_count=10,
            similarity_scores=[0.95, 0.88, 0.82],
            latency_ms=100,
        )
        ```
    """

    rag_event_type: RAGEventType | None = None
    query: str | None = None
    document_count: int | None = None
    chunk_count: int | None = None
    embedding_model: str | None = None
    reranker_model: str | None = None
    top_k: int | None = None
    similarity_scores: list[float] = field(default_factory=list)
    latency_ms: float | None = None
    collection_name: str | None = None

    @classmethod
    def create(
        cls,
        event_type: RAGEventType,
        query: str | None = None,
        document_count: int | None = None,
        chunk_count: int | None = None,
        embedding_model: str | None = None,
        reranker_model: str | None = None,
        top_k: int | None = None,
        similarity_scores: list[float] | None = None,
        latency_ms: float | None = None,
        collection_name: str | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> RAGEvent:
        """
        Factory method to create a RAG event.

        Args:
            event_type: Type of RAG event
            query: Query text
            document_count: Number of documents
            chunk_count: Number of chunks
            embedding_model: Embedding model
            reranker_model: Reranker model
            top_k: Number of results
            similarity_scores: Document scores
            latency_ms: Operation latency
            collection_name: Collection name
            severity: Event severity
            correlation_id: Correlation ID
            metadata: Additional metadata
            tags: Event tags

        Returns:
            New RAGEvent instance
        """
        # Auto-set severity for error events
        if event_type == RAGEventType.ERROR and severity == EventSeverity.INFO:
            severity = EventSeverity.ERROR

        return cls(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC),
            source="rag_pipeline",
            event_type=event_type.value,
            severity=severity,
            correlation_id=correlation_id or str(uuid.uuid4())[:12],
            metadata=metadata or {},
            tags=tags or ["rag"],
            rag_event_type=event_type,
            query=query,
            document_count=document_count,
            chunk_count=chunk_count,
            embedding_model=embedding_model,
            reranker_model=reranker_model,
            top_k=top_k,
            similarity_scores=similarity_scores or [],
            latency_ms=latency_ms,
            collection_name=collection_name,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        base_dict = super().to_dict()
        base_dict.update(
            {
                "rag_event_type": (self.rag_event_type.value if self.rag_event_type else None),
                "query": self.query,
                "document_count": self.document_count,
                "chunk_count": self.chunk_count,
                "embedding_model": self.embedding_model,
                "reranker_model": self.reranker_model,
                "top_k": self.top_k,
                "similarity_scores": self.similarity_scores,
                "latency_ms": self.latency_ms,
                "collection_name": self.collection_name,
            }
        )
        return base_dict

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RAGEvent:
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        else:
            timestamp = datetime.now(UTC)

        rag_event_type = data.get("rag_event_type")
        if rag_event_type:
            rag_event_type = RAGEventType(rag_event_type)

        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            timestamp=timestamp,
            source=data["source"],
            event_type=data["event_type"],
            severity=EventSeverity(data.get("severity", "info")),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            rag_event_type=rag_event_type,
            query=data.get("query"),
            document_count=data.get("document_count"),
            chunk_count=data.get("chunk_count"),
            embedding_model=data.get("embedding_model"),
            reranker_model=data.get("reranker_model"),
            top_k=data.get("top_k"),
            similarity_scores=data.get("similarity_scores", []),
            latency_ms=data.get("latency_ms"),
            collection_name=data.get("collection_name"),
        )


# =============================================================================
# Security Event
# =============================================================================


@dataclass
class SecurityEvent(BaseEvent):
    """
    Event for security-related activities.

    Captures authentication, authorization, and security violations.

    Attributes:
        security_event_type: Specific security event type
        user_id: User identifier
        resource_type: Type of resource accessed
        resource_id: Resource identifier
        action: Action attempted
        granted: Whether access was granted
        reason: Reason for decision
        ip_address: Client IP address
        user_agent: Client user agent
        violation_type: Type of violation (for violation events)

    Example:
        ```python
        # Authentication event
        event = SecurityEvent.create(
            event_type=SecurityEventType.AUTH_SUCCESS,
            user_id="user_123",
            ip_address="192.168.1.100",
        )

        # Access denied event
        denied_event = SecurityEvent.create(
            event_type=SecurityEventType.ACCESS_DENIED,
            user_id="user_123",
            resource_type="document",
            resource_id="doc_456",
            action="delete",
            reason="Insufficient permissions",
        )

        # Security violation event
        violation_event = SecurityEvent.create(
            event_type=SecurityEventType.VIOLATION,
            user_id="user_123",
            violation_type="injection_attempt",
            severity=EventSeverity.CRITICAL,
        )
        ```
    """

    security_event_type: SecurityEventType | None = None
    user_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    action: str | None = None
    granted: bool | None = None
    reason: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    violation_type: str | None = None

    @classmethod
    def create(
        cls,
        event_type: SecurityEventType,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        action: str | None = None,
        granted: bool | None = None,
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        violation_type: str | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> SecurityEvent:
        """
        Factory method to create a security event.

        Args:
            event_type: Type of security event
            user_id: User identifier
            resource_type: Resource type
            resource_id: Resource identifier
            action: Action attempted
            granted: Whether access granted
            reason: Decision reason
            ip_address: Client IP
            user_agent: Client user agent
            violation_type: Violation type
            severity: Event severity
            correlation_id: Correlation ID
            metadata: Additional metadata
            tags: Event tags

        Returns:
            New SecurityEvent instance
        """
        # Auto-set severity based on event type
        if event_type == SecurityEventType.VIOLATION and severity == EventSeverity.INFO:
            severity = EventSeverity.CRITICAL
        elif (
            event_type
            in (
                SecurityEventType.AUTH_FAILURE,
                SecurityEventType.ACCESS_DENIED,
            )
            and severity == EventSeverity.INFO
        ):
            severity = EventSeverity.WARNING

        return cls(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC),
            source="security",
            event_type=event_type.value,
            severity=severity,
            correlation_id=correlation_id or str(uuid.uuid4())[:12],
            metadata=metadata or {},
            tags=tags or ["security"],
            security_event_type=event_type,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            granted=granted,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
            violation_type=violation_type,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        base_dict = super().to_dict()
        base_dict.update(
            {
                "security_event_type": (
                    self.security_event_type.value if self.security_event_type else None
                ),
                "user_id": self.user_id,
                "resource_type": self.resource_type,
                "resource_id": self.resource_id,
                "action": self.action,
                "granted": self.granted,
                "reason": self.reason,
                "ip_address": self.ip_address,
                "user_agent": self.user_agent,
                "violation_type": self.violation_type,
            }
        )
        return base_dict

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecurityEvent:
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        else:
            timestamp = datetime.now(UTC)

        security_event_type = data.get("security_event_type")
        if security_event_type:
            security_event_type = SecurityEventType(security_event_type)

        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            timestamp=timestamp,
            source=data["source"],
            event_type=data["event_type"],
            severity=EventSeverity(data.get("severity", "info")),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            security_event_type=security_event_type,
            user_id=data.get("user_id"),
            resource_type=data.get("resource_type"),
            resource_id=data.get("resource_id"),
            action=data.get("action"),
            granted=data.get("granted"),
            reason=data.get("reason"),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            violation_type=data.get("violation_type"),
        )


# =============================================================================
# System Event
# =============================================================================


@dataclass
class SystemEvent(BaseEvent):
    """
    Event for system-level activities.

    Captures system startup, shutdown, health checks, and configuration.

    Attributes:
        system_event_type: Specific system event type
        component: System component name
        status: Component status
        message: Status message
        health_status: Health check result
        config_key: Configuration key changed
        old_value: Previous configuration value
        new_value: New configuration value
        resource_type: Resource type (for limit events)
        resource_usage: Current resource usage
        resource_limit: Resource limit

    Example:
        ```python
        # System startup event
        event = SystemEvent.create(
            event_type=SystemEventType.STARTUP,
            component="agent_service",
            message="Service started successfully",
        )

        # Health check event
        health_event = SystemEvent.create(
            event_type=SystemEventType.HEALTH_CHECK,
            component="database",
            status="healthy",
            health_status={"latency_ms": 5, "connections": 10},
        )

        # Resource limit event
        limit_event = SystemEvent.create(
            event_type=SystemEventType.RESOURCE_LIMIT,
            component="memory",
            resource_type="heap",
            resource_usage=0.85,
            resource_limit=0.9,
            severity=EventSeverity.WARNING,
        )
        ```
    """

    system_event_type: SystemEventType | None = None
    component: str = ""
    status: str | None = None
    message: str | None = None
    health_status: dict[str, Any] = field(default_factory=dict)
    config_key: str | None = None
    old_value: Any | None = None
    new_value: Any | None = None
    resource_type: str | None = None
    resource_usage: float | None = None
    resource_limit: float | None = None

    @classmethod
    def create(
        cls,
        event_type: SystemEventType,
        component: str,
        status: str | None = None,
        message: str | None = None,
        health_status: dict[str, Any] | None = None,
        config_key: str | None = None,
        old_value: Any | None = None,
        new_value: Any | None = None,
        resource_type: str | None = None,
        resource_usage: float | None = None,
        resource_limit: float | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> SystemEvent:
        """
        Factory method to create a system event.

        Args:
            event_type: Type of system event
            component: Component name
            status: Component status
            message: Status message
            health_status: Health check results
            config_key: Configuration key
            old_value: Previous value
            new_value: New value
            resource_type: Resource type
            resource_usage: Current usage
            resource_limit: Usage limit
            severity: Event severity
            correlation_id: Correlation ID
            metadata: Additional metadata
            tags: Event tags

        Returns:
            New SystemEvent instance
        """
        # Auto-set severity based on event type
        if event_type == SystemEventType.ERROR and severity == EventSeverity.INFO:
            severity = EventSeverity.ERROR
        elif event_type == SystemEventType.WARNING and severity == EventSeverity.INFO:
            severity = EventSeverity.WARNING

        return cls(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC),
            source=f"system:{component}",
            event_type=event_type.value,
            severity=severity,
            correlation_id=correlation_id or str(uuid.uuid4())[:12],
            metadata=metadata or {},
            tags=tags or ["system"],
            system_event_type=event_type,
            component=component,
            status=status,
            message=message,
            health_status=health_status or {},
            config_key=config_key,
            old_value=old_value,
            new_value=new_value,
            resource_type=resource_type,
            resource_usage=resource_usage,
            resource_limit=resource_limit,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        base_dict = super().to_dict()
        base_dict.update(
            {
                "system_event_type": (
                    self.system_event_type.value if self.system_event_type else None
                ),
                "component": self.component,
                "status": self.status,
                "message": self.message,
                "health_status": self.health_status,
                "config_key": self.config_key,
                "old_value": self.old_value,
                "new_value": self.new_value,
                "resource_type": self.resource_type,
                "resource_usage": self.resource_usage,
                "resource_limit": self.resource_limit,
            }
        )
        return base_dict

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SystemEvent:
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        else:
            timestamp = datetime.now(UTC)

        system_event_type = data.get("system_event_type")
        if system_event_type:
            system_event_type = SystemEventType(system_event_type)

        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            timestamp=timestamp,
            source=data["source"],
            event_type=data["event_type"],
            severity=EventSeverity(data.get("severity", "info")),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            system_event_type=system_event_type,
            component=data.get("component", ""),
            status=data.get("status"),
            message=data.get("message"),
            health_status=data.get("health_status", {}),
            config_key=data.get("config_key"),
            old_value=data.get("old_value"),
            new_value=data.get("new_value"),
            resource_type=data.get("resource_type"),
            resource_usage=data.get("resource_usage"),
            resource_limit=data.get("resource_limit"),
        )


__all__ = [
    # Enums
    "EventSeverity",
    "AgentEventType",
    "ToolEventType",
    "LLMEventType",
    "RAGEventType",
    "SecurityEventType",
    "SystemEventType",
    # Events
    "BaseEvent",
    "AgentEvent",
    "ToolEvent",
    "LLMEvent",
    "RAGEvent",
    "SecurityEvent",
    "SystemEvent",
]
