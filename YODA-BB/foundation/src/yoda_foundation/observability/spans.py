"""
Semantic conventions for agent spans.

This module defines standardized attribute names and helper functions
for creating spans that follow OpenTelemetry semantic conventions
specific to agentic AI systems.

Example:
    ```python
    from yoda_foundation.observability.spans import (
        AgentSpanAttributes,
        LLMSpanAttributes,
        ToolSpanAttributes,
        RAGSpanAttributes,
        create_agent_span_attributes,
        create_llm_span_attributes,
    )

    # Create standardized attributes for an agent span
    attrs = create_agent_span_attributes(
        agent_name="research_agent",
        agent_version="1.0.0",
        task_id="task_123",
        iteration=3,
    )

    # Create attributes for an LLM call
    llm_attrs = create_llm_span_attributes(
        model="gpt-4",
        provider="openai",
        input_tokens=100,
        output_tokens=50,
    )
    ```
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SpanKind(Enum):
    """
    Span kind types for agent operations.

    Follows OpenTelemetry SpanKind conventions with additions
    for agentic AI patterns.
    """

    INTERNAL = "internal"
    CLIENT = "client"
    SERVER = "server"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class AgentSpanAttributes:
    """
    Standard attribute names for agent spans.

    These attributes follow OpenTelemetry semantic conventions
    with extensions for agentic AI systems.

    Example:
        ```python
        span.set_attribute(AgentSpanAttributes.AGENT_NAME, "summarizer")
        span.set_attribute(AgentSpanAttributes.AGENT_VERSION, "1.0.0")
        span.set_attribute(AgentSpanAttributes.ITERATION, 3)
        ```
    """

    # Agent identification
    AGENT_NAME = "agent.name"
    AGENT_VERSION = "agent.version"
    AGENT_TYPE = "agent.type"
    AGENT_ID = "agent.id"

    # Execution context
    TASK_ID = "agent.task.id"
    TASK_TYPE = "agent.task.type"
    GOAL = "agent.goal"
    ITERATION = "agent.iteration"
    MAX_ITERATIONS = "agent.max_iterations"

    # Status and results
    STATUS = "agent.status"
    RESULT_TYPE = "agent.result.type"
    ERROR_TYPE = "agent.error.type"
    ERROR_MESSAGE = "agent.error.message"

    # Performance
    EXECUTION_TIME_MS = "agent.execution_time_ms"
    TOTAL_TOKENS = "agent.total_tokens"
    TOTAL_COST_CENTS = "agent.total_cost_cents"

    # Capabilities
    CAPABILITIES = "agent.capabilities"
    TOOLS_AVAILABLE = "agent.tools_available"
    TOOLS_USED = "agent.tools_used"

    # Memory
    MEMORY_ENABLED = "agent.memory.enabled"
    MEMORY_SIZE = "agent.memory.size"

    # Security
    USER_ID = "agent.user_id"
    SESSION_ID = "agent.session_id"
    TENANT_ID = "agent.tenant_id"


class LLMSpanAttributes:
    """
    Standard attribute names for LLM call spans.

    These attributes capture details about LLM API calls
    for debugging and cost tracking.

    Example:
        ```python
        span.set_attribute(LLMSpanAttributes.MODEL, "gpt-4")
        span.set_attribute(LLMSpanAttributes.INPUT_TOKENS, 500)
        span.set_attribute(LLMSpanAttributes.OUTPUT_TOKENS, 150)
        ```
    """

    # Model identification
    MODEL = "llm.model"
    MODEL_VERSION = "llm.model_version"
    PROVIDER = "llm.provider"
    API_BASE = "llm.api_base"

    # Request parameters
    TEMPERATURE = "llm.temperature"
    MAX_TOKENS = "llm.max_tokens"
    TOP_P = "llm.top_p"
    FREQUENCY_PENALTY = "llm.frequency_penalty"
    PRESENCE_PENALTY = "llm.presence_penalty"
    STOP_SEQUENCES = "llm.stop_sequences"

    # Token usage
    INPUT_TOKENS = "llm.input_tokens"
    OUTPUT_TOKENS = "llm.output_tokens"
    TOTAL_TOKENS = "llm.total_tokens"

    # Cost
    COST_CENTS = "llm.cost_cents"
    INPUT_COST_CENTS = "llm.input_cost_cents"
    OUTPUT_COST_CENTS = "llm.output_cost_cents"

    # Performance
    TIME_TO_FIRST_TOKEN_MS = "llm.time_to_first_token_ms"
    LATENCY_MS = "llm.latency_ms"

    # Request/Response
    REQUEST_ID = "llm.request_id"
    FINISH_REASON = "llm.finish_reason"
    STREAM = "llm.stream"

    # Content (be careful with PII)
    PROMPT_TEMPLATE = "llm.prompt_template"
    SYSTEM_MESSAGE_LENGTH = "llm.system_message_length"
    USER_MESSAGE_LENGTH = "llm.user_message_length"


class ToolSpanAttributes:
    """
    Standard attribute names for tool execution spans.

    These attributes capture details about tool invocations
    for debugging and monitoring.

    Example:
        ```python
        span.set_attribute(ToolSpanAttributes.TOOL_NAME, "search")
        span.set_attribute(ToolSpanAttributes.TOOL_VERSION, "1.0.0")
        span.set_attribute(ToolSpanAttributes.EXECUTION_TIME_MS, 250)
        ```
    """

    # Tool identification
    TOOL_NAME = "tool.name"
    TOOL_VERSION = "tool.version"
    TOOL_TYPE = "tool.type"
    TOOL_ID = "tool.id"

    # Execution context
    EXECUTION_ID = "tool.execution_id"
    ATTEMPT_NUMBER = "tool.attempt_number"
    MAX_RETRIES = "tool.max_retries"

    # Parameters
    PARAMETER_COUNT = "tool.parameter_count"
    PARAMETER_NAMES = "tool.parameter_names"

    # Results
    SUCCESS = "tool.success"
    RESULT_TYPE = "tool.result.type"
    RESULT_SIZE_BYTES = "tool.result.size_bytes"
    ERROR_TYPE = "tool.error.type"
    ERROR_MESSAGE = "tool.error.message"
    RETRYABLE = "tool.retryable"

    # Performance
    EXECUTION_TIME_MS = "tool.execution_time_ms"
    CACHE_HIT = "tool.cache_hit"

    # Resource usage
    API_CALLS = "tool.api_calls"
    COST_CENTS = "tool.cost_cents"


class RAGSpanAttributes:
    """
    Standard attribute names for RAG operation spans.

    These attributes capture details about retrieval-augmented
    generation operations.

    Example:
        ```python
        span.set_attribute(RAGSpanAttributes.QUERY, "What is machine learning?")
        span.set_attribute(RAGSpanAttributes.TOP_K, 5)
        span.set_attribute(RAGSpanAttributes.DOCUMENTS_RETRIEVED, 5)
        ```
    """

    # Query
    QUERY = "rag.query"
    QUERY_EMBEDDING_MODEL = "rag.query_embedding_model"
    QUERY_EMBEDDING_DIMENSION = "rag.query_embedding_dimension"

    # Retrieval parameters
    TOP_K = "rag.top_k"
    SIMILARITY_THRESHOLD = "rag.similarity_threshold"
    FILTER_CONDITIONS = "rag.filter_conditions"

    # Retrieval results
    DOCUMENTS_RETRIEVED = "rag.documents_retrieved"
    DOCUMENTS_RERANKED = "rag.documents_reranked"
    MIN_SIMILARITY_SCORE = "rag.min_similarity_score"
    MAX_SIMILARITY_SCORE = "rag.max_similarity_score"
    AVG_SIMILARITY_SCORE = "rag.avg_similarity_score"

    # Vector store
    VECTOR_STORE_TYPE = "rag.vector_store.type"
    VECTOR_STORE_COLLECTION = "rag.vector_store.collection"
    VECTOR_STORE_INDEX = "rag.vector_store.index"

    # Performance
    EMBEDDING_TIME_MS = "rag.embedding_time_ms"
    RETRIEVAL_TIME_MS = "rag.retrieval_time_ms"
    RERANKING_TIME_MS = "rag.reranking_time_ms"
    TOTAL_TIME_MS = "rag.total_time_ms"

    # Context
    CONTEXT_TOKENS = "rag.context_tokens"
    CONTEXT_DOCUMENTS = "rag.context_documents"
    CONTEXT_TRUNCATED = "rag.context_truncated"


@dataclass
class SpanContext:
    """
    Container for span context information.

    Attributes:
        trace_id: The trace identifier
        span_id: The span identifier
        trace_flags: Trace flags (sampled, etc.)
        trace_state: Additional trace state
        is_remote: Whether this context came from a remote service

    Example:
        ```python
        ctx = SpanContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            trace_flags=1,
        )
        ```
    """

    trace_id: str
    span_id: str
    trace_flags: int = 1
    trace_state: str | None = None
    is_remote: bool = False

    @property
    def is_valid(self) -> bool:
        """Check if the context is valid."""
        return bool(self.trace_id and self.span_id)

    @property
    def is_sampled(self) -> bool:
        """Check if the trace is sampled."""
        return bool(self.trace_flags & 1)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "trace_flags": self.trace_flags,
            "trace_state": self.trace_state,
            "is_remote": self.is_remote,
        }


def create_agent_span_attributes(
    agent_name: str,
    agent_version: str = "1.0.0",
    agent_type: str | None = None,
    agent_id: str | None = None,
    task_id: str | None = None,
    task_type: str | None = None,
    goal: str | None = None,
    iteration: int | None = None,
    max_iterations: int | None = None,
    capabilities: list[str] | None = None,
    tools_available: list[str] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Create standardized attributes for an agent span.

    Args:
        agent_name: Name of the agent
        agent_version: Version of the agent
        agent_type: Type of agent (e.g., "react", "cot")
        agent_id: Unique identifier for the agent instance
        task_id: Identifier for the current task
        task_type: Type of task being executed
        goal: The goal or objective of the task
        iteration: Current iteration number
        max_iterations: Maximum allowed iterations
        capabilities: List of agent capabilities
        tools_available: List of available tools
        user_id: User identifier
        session_id: Session identifier
        tenant_id: Tenant identifier

    Returns:
        Dictionary of span attributes

    Example:
        ```python
        attrs = create_agent_span_attributes(
            agent_name="research_agent",
            agent_version="1.0.0",
            task_id="task_123",
            iteration=3,
            max_iterations=10,
            tools_available=["search", "summarize"],
        )
        span.set_attributes(attrs)
        ```
    """
    attrs: dict[str, Any] = {
        AgentSpanAttributes.AGENT_NAME: agent_name,
        AgentSpanAttributes.AGENT_VERSION: agent_version,
    }

    if agent_type is not None:
        attrs[AgentSpanAttributes.AGENT_TYPE] = agent_type
    if agent_id is not None:
        attrs[AgentSpanAttributes.AGENT_ID] = agent_id
    if task_id is not None:
        attrs[AgentSpanAttributes.TASK_ID] = task_id
    if task_type is not None:
        attrs[AgentSpanAttributes.TASK_TYPE] = task_type
    if goal is not None:
        attrs[AgentSpanAttributes.GOAL] = goal
    if iteration is not None:
        attrs[AgentSpanAttributes.ITERATION] = iteration
    if max_iterations is not None:
        attrs[AgentSpanAttributes.MAX_ITERATIONS] = max_iterations
    if capabilities is not None:
        attrs[AgentSpanAttributes.CAPABILITIES] = capabilities
    if tools_available is not None:
        attrs[AgentSpanAttributes.TOOLS_AVAILABLE] = tools_available
    if user_id is not None:
        attrs[AgentSpanAttributes.USER_ID] = user_id
    if session_id is not None:
        attrs[AgentSpanAttributes.SESSION_ID] = session_id
    if tenant_id is not None:
        attrs[AgentSpanAttributes.TENANT_ID] = tenant_id

    return attrs


def create_llm_span_attributes(
    model: str,
    provider: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_cents: float | None = None,
    latency_ms: float | None = None,
    time_to_first_token_ms: float | None = None,
    request_id: str | None = None,
    finish_reason: str | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """
    Create standardized attributes for an LLM call span.

    Args:
        model: The LLM model name
        provider: The LLM provider (e.g., "openai", "anthropic")
        temperature: Temperature setting
        max_tokens: Maximum tokens setting
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cost_cents: Cost of the call in cents
        latency_ms: Total latency in milliseconds
        time_to_first_token_ms: Time to first token for streaming
        request_id: Request identifier from the provider
        finish_reason: Reason for completion (e.g., "stop", "length")
        stream: Whether streaming was enabled

    Returns:
        Dictionary of span attributes

    Example:
        ```python
        attrs = create_llm_span_attributes(
            model="gpt-4",
            provider="openai",
            input_tokens=500,
            output_tokens=150,
            latency_ms=1250.5,
        )
        span.set_attributes(attrs)
        ```
    """
    attrs: dict[str, Any] = {
        LLMSpanAttributes.MODEL: model,
        LLMSpanAttributes.STREAM: stream,
    }

    if provider is not None:
        attrs[LLMSpanAttributes.PROVIDER] = provider
    if temperature is not None:
        attrs[LLMSpanAttributes.TEMPERATURE] = temperature
    if max_tokens is not None:
        attrs[LLMSpanAttributes.MAX_TOKENS] = max_tokens
    if input_tokens is not None:
        attrs[LLMSpanAttributes.INPUT_TOKENS] = input_tokens
    if output_tokens is not None:
        attrs[LLMSpanAttributes.OUTPUT_TOKENS] = output_tokens
    if input_tokens is not None and output_tokens is not None:
        attrs[LLMSpanAttributes.TOTAL_TOKENS] = input_tokens + output_tokens
    if cost_cents is not None:
        attrs[LLMSpanAttributes.COST_CENTS] = cost_cents
    if latency_ms is not None:
        attrs[LLMSpanAttributes.LATENCY_MS] = latency_ms
    if time_to_first_token_ms is not None:
        attrs[LLMSpanAttributes.TIME_TO_FIRST_TOKEN_MS] = time_to_first_token_ms
    if request_id is not None:
        attrs[LLMSpanAttributes.REQUEST_ID] = request_id
    if finish_reason is not None:
        attrs[LLMSpanAttributes.FINISH_REASON] = finish_reason

    return attrs


def create_tool_span_attributes(
    tool_name: str,
    tool_version: str = "1.0.0",
    tool_type: str | None = None,
    execution_id: str | None = None,
    attempt_number: int = 1,
    max_retries: int | None = None,
    parameter_count: int | None = None,
    parameter_names: list[str] | None = None,
    success: bool | None = None,
    execution_time_ms: float | None = None,
    cache_hit: bool = False,
) -> dict[str, Any]:
    """
    Create standardized attributes for a tool execution span.

    Args:
        tool_name: Name of the tool
        tool_version: Version of the tool
        tool_type: Type of tool
        execution_id: Unique execution identifier
        attempt_number: Current attempt number
        max_retries: Maximum retry attempts
        parameter_count: Number of parameters
        parameter_names: Names of parameters
        success: Whether execution was successful
        execution_time_ms: Execution time in milliseconds
        cache_hit: Whether result was from cache

    Returns:
        Dictionary of span attributes

    Example:
        ```python
        attrs = create_tool_span_attributes(
            tool_name="search",
            tool_version="1.0.0",
            execution_time_ms=250.0,
            success=True,
            cache_hit=False,
        )
        span.set_attributes(attrs)
        ```
    """
    attrs: dict[str, Any] = {
        ToolSpanAttributes.TOOL_NAME: tool_name,
        ToolSpanAttributes.TOOL_VERSION: tool_version,
        ToolSpanAttributes.ATTEMPT_NUMBER: attempt_number,
        ToolSpanAttributes.CACHE_HIT: cache_hit,
    }

    if tool_type is not None:
        attrs[ToolSpanAttributes.TOOL_TYPE] = tool_type
    if execution_id is not None:
        attrs[ToolSpanAttributes.EXECUTION_ID] = execution_id
    if max_retries is not None:
        attrs[ToolSpanAttributes.MAX_RETRIES] = max_retries
    if parameter_count is not None:
        attrs[ToolSpanAttributes.PARAMETER_COUNT] = parameter_count
    if parameter_names is not None:
        attrs[ToolSpanAttributes.PARAMETER_NAMES] = parameter_names
    if success is not None:
        attrs[ToolSpanAttributes.SUCCESS] = success
    if execution_time_ms is not None:
        attrs[ToolSpanAttributes.EXECUTION_TIME_MS] = execution_time_ms

    return attrs


def create_rag_span_attributes(
    query: str | None = None,
    query_embedding_model: str | None = None,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
    documents_retrieved: int | None = None,
    documents_reranked: int | None = None,
    min_similarity_score: float | None = None,
    max_similarity_score: float | None = None,
    avg_similarity_score: float | None = None,
    vector_store_type: str | None = None,
    vector_store_collection: str | None = None,
    embedding_time_ms: float | None = None,
    retrieval_time_ms: float | None = None,
    reranking_time_ms: float | None = None,
    total_time_ms: float | None = None,
    context_tokens: int | None = None,
    context_truncated: bool = False,
) -> dict[str, Any]:
    """
    Create standardized attributes for a RAG operation span.

    Args:
        query: The query string
        query_embedding_model: Model used for query embedding
        top_k: Number of documents to retrieve
        similarity_threshold: Minimum similarity threshold
        documents_retrieved: Number of documents retrieved
        documents_reranked: Number of documents after reranking
        min_similarity_score: Minimum similarity score
        max_similarity_score: Maximum similarity score
        avg_similarity_score: Average similarity score
        vector_store_type: Type of vector store
        vector_store_collection: Collection name
        embedding_time_ms: Time for embedding
        retrieval_time_ms: Time for retrieval
        reranking_time_ms: Time for reranking
        total_time_ms: Total time for RAG operation
        context_tokens: Number of tokens in context
        context_truncated: Whether context was truncated

    Returns:
        Dictionary of span attributes

    Example:
        ```python
        attrs = create_rag_span_attributes(
            query="What is machine learning?",
            top_k=5,
            documents_retrieved=5,
            retrieval_time_ms=125.0,
            avg_similarity_score=0.85,
        )
        span.set_attributes(attrs)
        ```
    """
    attrs: dict[str, Any] = {
        RAGSpanAttributes.CONTEXT_TRUNCATED: context_truncated,
    }

    if query is not None:
        # Truncate query to avoid huge span attributes
        attrs[RAGSpanAttributes.QUERY] = query[:500] if len(query) > 500 else query
    if query_embedding_model is not None:
        attrs[RAGSpanAttributes.QUERY_EMBEDDING_MODEL] = query_embedding_model
    if top_k is not None:
        attrs[RAGSpanAttributes.TOP_K] = top_k
    if similarity_threshold is not None:
        attrs[RAGSpanAttributes.SIMILARITY_THRESHOLD] = similarity_threshold
    if documents_retrieved is not None:
        attrs[RAGSpanAttributes.DOCUMENTS_RETRIEVED] = documents_retrieved
    if documents_reranked is not None:
        attrs[RAGSpanAttributes.DOCUMENTS_RERANKED] = documents_reranked
    if min_similarity_score is not None:
        attrs[RAGSpanAttributes.MIN_SIMILARITY_SCORE] = min_similarity_score
    if max_similarity_score is not None:
        attrs[RAGSpanAttributes.MAX_SIMILARITY_SCORE] = max_similarity_score
    if avg_similarity_score is not None:
        attrs[RAGSpanAttributes.AVG_SIMILARITY_SCORE] = avg_similarity_score
    if vector_store_type is not None:
        attrs[RAGSpanAttributes.VECTOR_STORE_TYPE] = vector_store_type
    if vector_store_collection is not None:
        attrs[RAGSpanAttributes.VECTOR_STORE_COLLECTION] = vector_store_collection
    if embedding_time_ms is not None:
        attrs[RAGSpanAttributes.EMBEDDING_TIME_MS] = embedding_time_ms
    if retrieval_time_ms is not None:
        attrs[RAGSpanAttributes.RETRIEVAL_TIME_MS] = retrieval_time_ms
    if reranking_time_ms is not None:
        attrs[RAGSpanAttributes.RERANKING_TIME_MS] = reranking_time_ms
    if total_time_ms is not None:
        attrs[RAGSpanAttributes.TOTAL_TIME_MS] = total_time_ms
    if context_tokens is not None:
        attrs[RAGSpanAttributes.CONTEXT_TOKENS] = context_tokens

    return attrs
