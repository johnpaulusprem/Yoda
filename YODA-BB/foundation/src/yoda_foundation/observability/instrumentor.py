"""
Auto-instrumentation for library components.

This module provides instrumentors that automatically add tracing and metrics
to agent, tool, LLM, and RAG components.

Example:
    ```python
    from yoda_foundation.observability import (
        AgentInstrumentor,
        ToolInstrumentor,
        LLMInstrumentor,
        RAGInstrumentor,
        instrument_all,
        uninstrument_all,
    )

    # Instrument all components
    instrument_all()

    # Or instrument selectively
    AgentInstrumentor().instrument()
    ToolInstrumentor().instrument()
    LLMInstrumentor().instrument()

    # Remove instrumentation
    uninstrument_all()
    ```
"""

from __future__ import annotations

import functools
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yoda_foundation.observability.metrics import AgentMetrics, get_metrics
from yoda_foundation.observability.spans import (
    AgentSpanAttributes,
    LLMSpanAttributes,
    RAGSpanAttributes,
    SpanKind,
    ToolSpanAttributes,
    create_agent_span_attributes,
    create_llm_span_attributes,
    create_rag_span_attributes,
    create_tool_span_attributes,
)
from yoda_foundation.observability.tracer import (
    AgentTracer,
    SpanStatus,
    get_tracer,
)


@dataclass
class InstrumentorConfig:
    """
    Configuration for instrumentors.

    Attributes:
        enabled: Whether instrumentation is enabled
        trace_enabled: Whether to create spans
        metrics_enabled: Whether to collect metrics
        record_inputs: Whether to record input data
        record_outputs: Whether to record output data
        max_attribute_length: Maximum length for attribute values

    Example:
        ```python
        config = InstrumentorConfig(
            enabled=True,
            trace_enabled=True,
            metrics_enabled=True,
            record_inputs=True,
            max_attribute_length=500,
        )
        ```
    """

    enabled: bool = True
    trace_enabled: bool = True
    metrics_enabled: bool = True
    record_inputs: bool = False
    record_outputs: bool = False
    max_attribute_length: int = 500


class BaseInstrumentor(ABC):
    """
    Abstract base class for instrumentors.

    Instrumentors are responsible for wrapping library components
    to add tracing and metrics automatically.

    Example:
        ```python
        class CustomInstrumentor(BaseInstrumentor):
            def instrument(self) -> None:
                # Wrap methods with instrumentation
                pass

            def uninstrument(self) -> None:
                # Remove instrumentation
                pass
        ```
    """

    def __init__(
        self,
        tracer: AgentTracer | None = None,
        metrics: AgentMetrics | None = None,
        config: InstrumentorConfig | None = None,
    ) -> None:
        """
        Initialize the instrumentor.

        Args:
            tracer: Tracer to use (defaults to global)
            metrics: Metrics collector (defaults to global)
            config: Instrumentor configuration
        """
        self.tracer = tracer or get_tracer()
        self.metrics = metrics or get_metrics()
        self.config = config or InstrumentorConfig()
        self._instrumented = False
        self._original_methods: dict[str, Any] = {}

    @abstractmethod
    def instrument(self) -> None:
        """
        Apply instrumentation to the component.

        Should wrap relevant methods with tracing and metrics.
        """
        pass

    @abstractmethod
    def uninstrument(self) -> None:
        """
        Remove instrumentation from the component.

        Should restore original methods.
        """
        pass

    @property
    def is_instrumented(self) -> bool:
        """Check if instrumentation is applied."""
        return self._instrumented


class AgentInstrumentor(BaseInstrumentor):
    """
    Instrumentor for BaseAgent and subclasses.

    Adds tracing and metrics to agent execution methods.

    Example:
        ```python
        instrumentor = AgentInstrumentor()
        instrumentor.instrument()

        # Now all agents are automatically traced
        result = await agent.run(input, security_context)
        # Spans created: agent.run, agent.think, agent.act
        ```
    """

    def instrument(self) -> None:
        """
        Apply instrumentation to BaseAgent.

        Wraps:
        - run() - Main execution method
        - think() - Reasoning step
        - act() - Action execution
        - reflect() - Reflection step
        """
        if self._instrumented:
            return

        try:
            from yoda_foundation.foundation.agents.base import BaseAgent

            # Store original methods
            self._original_methods["run"] = BaseAgent.run
            self._original_methods["think"] = BaseAgent.think
            self._original_methods["act"] = BaseAgent.act
            self._original_methods["reflect"] = BaseAgent.reflect

            # Wrap methods
            BaseAgent.run = self._wrap_run(BaseAgent.run)
            BaseAgent.think = self._wrap_think(BaseAgent.think)
            BaseAgent.act = self._wrap_act(BaseAgent.act)
            BaseAgent.reflect = self._wrap_reflect(BaseAgent.reflect)

            self._instrumented = True

        except ImportError:
            # BaseAgent not available
            pass

    def uninstrument(self) -> None:
        """Remove instrumentation from BaseAgent."""
        if not self._instrumented:
            return

        try:
            from yoda_foundation.foundation.agents.base import BaseAgent

            # Restore original methods
            if "run" in self._original_methods:
                BaseAgent.run = self._original_methods["run"]
            if "think" in self._original_methods:
                BaseAgent.think = self._original_methods["think"]
            if "act" in self._original_methods:
                BaseAgent.act = self._original_methods["act"]
            if "reflect" in self._original_methods:
                BaseAgent.reflect = self._original_methods["reflect"]

            self._original_methods.clear()
            self._instrumented = False

        except ImportError:
            pass

    def _wrap_run(self, original_method: Callable) -> Callable:
        """Wrap the run method with instrumentation."""
        tracer = self.tracer
        metrics = self.metrics
        config = self.config

        @functools.wraps(original_method)
        async def wrapped(self, input, security_context, *args, **kwargs):
            if not config.enabled:
                return await original_method(self, input, security_context, *args, **kwargs)

            # Create attributes
            attrs = create_agent_span_attributes(
                agent_name=self.name,
                agent_version=self.version,
                agent_type=self.__class__.__name__,
                max_iterations=self.config.max_iterations
                if hasattr(self.config, "max_iterations")
                else None,
                user_id=getattr(security_context, "user_id", None),
            )

            start_time = time.perf_counter()

            async with tracer.async_span(
                f"agent.run.{self.name}",
                kind=SpanKind.INTERNAL,
                attributes=attrs,
            ) as span:
                try:
                    result = await original_method(self, input, security_context, *args, **kwargs)

                    # Add result attributes
                    if hasattr(result, "iterations"):
                        span.set_attribute(AgentSpanAttributes.ITERATION, result.iterations)
                    if hasattr(result, "execution_time_ms"):
                        span.set_attribute(
                            AgentSpanAttributes.EXECUTION_TIME_MS, result.execution_time_ms
                        )

                    span.set_status(SpanStatus.OK)

                    # Record metrics
                    duration = time.perf_counter() - start_time
                    metrics.record_agent_request(
                        agent_name=self.name,
                        duration_seconds=duration,
                        success=True,
                        tokens_used=getattr(result, "tokens_used", None),
                        iterations=getattr(result, "iterations", None),
                    )

                    return result

                except (
                    BaseException
                ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                    span.record_exception(e)
                    span.set_status(SpanStatus.ERROR, str(e))

                    duration = time.perf_counter() - start_time
                    metrics.record_agent_request(
                        agent_name=self.name,
                        duration_seconds=duration,
                        success=False,
                        error_type=type(e).__name__,
                    )

                    raise

        return wrapped

    def _wrap_think(self, original_method: Callable) -> Callable:
        """Wrap the think method with instrumentation."""
        tracer = self.tracer
        config = self.config

        @functools.wraps(original_method)
        async def wrapped(self, context, *args, **kwargs):
            if not config.enabled:
                return await original_method(self, context, *args, **kwargs)

            iteration = getattr(context, "iteration", None)
            attrs = {
                AgentSpanAttributes.AGENT_NAME: self.name,
            }
            if iteration is not None:
                attrs[AgentSpanAttributes.ITERATION] = iteration

            async with tracer.async_span(
                f"agent.think.{self.name}",
                kind=SpanKind.INTERNAL,
                attributes=attrs,
            ) as span:
                try:
                    result = await original_method(self, context, *args, **kwargs)
                    span.set_status(SpanStatus.OK)
                    return result
                except (
                    BaseException
                ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                    span.record_exception(e)
                    span.set_status(SpanStatus.ERROR, str(e))
                    raise

        return wrapped

    def _wrap_act(self, original_method: Callable) -> Callable:
        """Wrap the act method with instrumentation."""
        tracer = self.tracer
        config = self.config

        @functools.wraps(original_method)
        async def wrapped(self, action, context, *args, **kwargs):
            if not config.enabled:
                return await original_method(self, action, context, *args, **kwargs)

            attrs = {
                AgentSpanAttributes.AGENT_NAME: self.name,
            }

            async with tracer.async_span(
                f"agent.act.{self.name}",
                kind=SpanKind.INTERNAL,
                attributes=attrs,
            ) as span:
                try:
                    result = await original_method(self, action, context, *args, **kwargs)
                    span.set_status(SpanStatus.OK)
                    return result
                except (
                    BaseException
                ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                    span.record_exception(e)
                    span.set_status(SpanStatus.ERROR, str(e))
                    raise

        return wrapped

    def _wrap_reflect(self, original_method: Callable) -> Callable:
        """Wrap the reflect method with instrumentation."""
        tracer = self.tracer
        config = self.config

        @functools.wraps(original_method)
        async def wrapped(self, result, context, *args, **kwargs):
            if not config.enabled:
                return await original_method(self, result, context, *args, **kwargs)

            async with tracer.async_span(
                f"agent.reflect.{self.name}",
                kind=SpanKind.INTERNAL,
                attributes={AgentSpanAttributes.AGENT_NAME: self.name},
            ) as span:
                try:
                    reflection = await original_method(self, result, context, *args, **kwargs)
                    span.set_status(SpanStatus.OK)
                    return reflection
                except (
                    BaseException
                ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                    span.record_exception(e)
                    span.set_status(SpanStatus.ERROR, str(e))
                    raise

        return wrapped


class ToolInstrumentor(BaseInstrumentor):
    """
    Instrumentor for BaseTool and subclasses.

    Adds tracing and metrics to tool execution.

    Example:
        ```python
        instrumentor = ToolInstrumentor()
        instrumentor.instrument()

        # Now all tools are automatically traced
        result = await tool.execute(params, security_context=ctx)
        # Span created: tool.execute.{tool_name}
        ```
    """

    def instrument(self) -> None:
        """Apply instrumentation to BaseTool."""
        if self._instrumented:
            return

        try:
            from yoda_foundation.foundation.tools import BaseTool

            self._original_methods["execute"] = BaseTool.execute
            BaseTool.execute = self._wrap_execute(BaseTool.execute)
            self._instrumented = True

        except ImportError:
            pass

    def uninstrument(self) -> None:
        """Remove instrumentation from BaseTool."""
        if not self._instrumented:
            return

        try:
            from yoda_foundation.foundation.tools import BaseTool

            if "execute" in self._original_methods:
                BaseTool.execute = self._original_methods["execute"]

            self._original_methods.clear()
            self._instrumented = False

        except ImportError:
            pass

    def _wrap_execute(self, original_method: Callable) -> Callable:
        """Wrap the execute method with instrumentation."""
        tracer = self.tracer
        metrics = self.metrics
        config = self.config

        @functools.wraps(original_method)
        async def wrapped(self, *args, **kwargs):
            if not config.enabled:
                return await original_method(self, *args, **kwargs)

            attrs = create_tool_span_attributes(
                tool_name=self.name,
                tool_version=getattr(self, "version", "1.0.0"),
                tool_type=self.__class__.__name__,
            )

            start_time = time.perf_counter()

            async with tracer.async_span(
                f"tool.execute.{self.name}",
                kind=SpanKind.CLIENT,
                attributes=attrs,
            ) as span:
                try:
                    result = await original_method(self, *args, **kwargs)

                    success = getattr(result, "success", True)
                    span.set_attribute(ToolSpanAttributes.SUCCESS, success)

                    if success:
                        span.set_status(SpanStatus.OK)
                    else:
                        span.set_status(SpanStatus.ERROR, getattr(result, "error", "Unknown error"))

                    duration = time.perf_counter() - start_time
                    cache_hit = getattr(result, "from_cache", False)

                    metrics.record_tool_execution(
                        tool_name=self.name,
                        duration_seconds=duration,
                        success=success,
                        cache_hit=cache_hit,
                    )

                    return result

                except (
                    BaseException
                ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                    span.record_exception(e)
                    span.set_status(SpanStatus.ERROR, str(e))

                    duration = time.perf_counter() - start_time
                    metrics.record_tool_execution(
                        tool_name=self.name,
                        duration_seconds=duration,
                        success=False,
                        error_type=type(e).__name__,
                    )

                    raise

        return wrapped


class LLMInstrumentor(BaseInstrumentor):
    """
    Instrumentor for LLM clients.

    Adds tracing and metrics to LLM API calls.

    Example:
        ```python
        instrumentor = LLMInstrumentor()
        instrumentor.instrument()

        # Now all LLM calls are automatically traced
        response = await llm_client.complete(request)
        # Span created: llm.complete
        ```
    """

    def instrument(self) -> None:
        """Apply instrumentation to LLM clients."""
        if self._instrumented:
            return

        try:
            from yoda_foundation.foundation.llm import BaseLLMClient

            self._original_methods["complete"] = BaseLLMClient.complete
            BaseLLMClient.complete = self._wrap_complete(BaseLLMClient.complete)
            self._instrumented = True

        except ImportError:
            pass

    def uninstrument(self) -> None:
        """Remove instrumentation from LLM clients."""
        if not self._instrumented:
            return

        try:
            from yoda_foundation.foundation.llm import BaseLLMClient

            if "complete" in self._original_methods:
                BaseLLMClient.complete = self._original_methods["complete"]

            self._original_methods.clear()
            self._instrumented = False

        except ImportError:
            pass

    def _wrap_complete(self, original_method: Callable) -> Callable:
        """Wrap the complete method with instrumentation."""
        tracer = self.tracer
        metrics = self.metrics
        config = self.config

        @functools.wraps(original_method)
        async def wrapped(self, request, *args, **kwargs):
            if not config.enabled:
                return await original_method(self, request, *args, **kwargs)

            model = getattr(request, "model", "unknown")
            attrs = create_llm_span_attributes(
                model=model,
                provider=getattr(self, "provider", None),
                temperature=getattr(request, "temperature", None),
                max_tokens=getattr(request, "max_tokens", None),
            )

            start_time = time.perf_counter()

            async with tracer.async_span(
                "llm.complete",
                kind=SpanKind.CLIENT,
                attributes=attrs,
            ) as span:
                try:
                    response = await original_method(self, request, *args, **kwargs)

                    # Add response attributes
                    input_tokens = getattr(response, "input_tokens", 0)
                    output_tokens = getattr(response, "output_tokens", 0)
                    cost_cents = getattr(response, "cost_cents", None)

                    span.set_attribute(LLMSpanAttributes.INPUT_TOKENS, input_tokens)
                    span.set_attribute(LLMSpanAttributes.OUTPUT_TOKENS, output_tokens)
                    span.set_attribute(LLMSpanAttributes.TOTAL_TOKENS, input_tokens + output_tokens)

                    if cost_cents is not None:
                        span.set_attribute(LLMSpanAttributes.COST_CENTS, cost_cents)

                    span.set_status(SpanStatus.OK)

                    duration = time.perf_counter() - start_time
                    metrics.record_llm_request(
                        model=model,
                        duration_seconds=duration,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_cents=cost_cents,
                        success=True,
                    )

                    return response

                except (
                    BaseException
                ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                    span.record_exception(e)
                    span.set_status(SpanStatus.ERROR, str(e))

                    duration = time.perf_counter() - start_time
                    metrics.record_llm_request(
                        model=model,
                        duration_seconds=duration,
                        success=False,
                        error_type=type(e).__name__,
                    )

                    raise

        return wrapped


class RAGInstrumentor(BaseInstrumentor):
    """
    Instrumentor for RAG pipeline components.

    Adds tracing and metrics to retrieval operations.

    Example:
        ```python
        instrumentor = RAGInstrumentor()
        instrumentor.instrument()

        # Now RAG operations are automatically traced
        docs = await retriever.retrieve(query)
        # Span created: rag.retrieve
        ```
    """

    def instrument(self) -> None:
        """Apply instrumentation to RAG retrievers."""
        if self._instrumented:
            return

        try:
            from yoda_foundation.rag.retrieval import BaseRetriever

            self._original_methods["retrieve"] = BaseRetriever.retrieve
            BaseRetriever.retrieve = self._wrap_retrieve(BaseRetriever.retrieve)
            self._instrumented = True

        except ImportError:
            pass

    def uninstrument(self) -> None:
        """Remove instrumentation from RAG retrievers."""
        if not self._instrumented:
            return

        try:
            from yoda_foundation.rag.retrieval import BaseRetriever

            if "retrieve" in self._original_methods:
                BaseRetriever.retrieve = self._original_methods["retrieve"]

            self._original_methods.clear()
            self._instrumented = False

        except ImportError:
            pass

    def _wrap_retrieve(self, original_method: Callable) -> Callable:
        """Wrap the retrieve method with instrumentation."""
        tracer = self.tracer
        metrics = self.metrics
        config = self.config

        @functools.wraps(original_method)
        async def wrapped(self, query, *args, **kwargs):
            if not config.enabled:
                return await original_method(self, query, *args, **kwargs)

            top_k = kwargs.get("top_k", getattr(self, "top_k", None))
            attrs = create_rag_span_attributes(
                query=query if config.record_inputs else None,
                top_k=top_k,
                vector_store_type=getattr(self, "vector_store_type", None),
            )

            start_time = time.perf_counter()

            async with tracer.async_span(
                "rag.retrieve",
                kind=SpanKind.CLIENT,
                attributes=attrs,
            ) as span:
                try:
                    documents = await original_method(self, query, *args, **kwargs)

                    num_docs = len(documents) if documents else 0
                    span.set_attribute(RAGSpanAttributes.DOCUMENTS_RETRIEVED, num_docs)
                    span.set_status(SpanStatus.OK)

                    duration = time.perf_counter() - start_time
                    collection = getattr(self, "collection", "default")

                    metrics.record_rag_retrieval(
                        collection=collection,
                        duration_seconds=duration,
                        documents_retrieved=num_docs,
                    )

                    return documents

                except (
                    BaseException
                ) as e:  # Intentionally broad: instrumentation catch-record-reraise
                    span.record_exception(e)
                    span.set_status(SpanStatus.ERROR, str(e))
                    raise

        return wrapped


class HTTPInstrumentor(BaseInstrumentor):
    """
    Instrumentor for HTTP clients (aiohttp, httpx).

    Note: For production use, prefer the official OpenTelemetry
    HTTP instrumentors.

    Example:
        ```python
        instrumentor = HTTPInstrumentor()
        instrumentor.instrument()
        ```
    """

    def instrument(self) -> None:
        """Apply instrumentation to HTTP clients."""
        if self._instrumented:
            return

        # Try to use OpenTelemetry's HTTP instrumentors
        try:
            from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor

            AioHttpClientInstrumentor().instrument()
            self._instrumented = True
        except ImportError:
            pass

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
            self._instrumented = True
        except ImportError:
            pass

    def uninstrument(self) -> None:
        """Remove instrumentation from HTTP clients."""
        if not self._instrumented:
            return

        try:
            from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor

            AioHttpClientInstrumentor().uninstrument()
        except ImportError:
            pass

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().uninstrument()
        except ImportError:
            pass

        self._instrumented = False


# Global instrumentor registry
_instrumentors: dict[str, BaseInstrumentor] = {}


def instrument_all(
    tracer: AgentTracer | None = None,
    metrics: AgentMetrics | None = None,
    config: InstrumentorConfig | None = None,
) -> None:
    """
    Instrument all supported components.

    Convenience function to apply all instrumentors at once.

    Args:
        tracer: Tracer to use (defaults to global)
        metrics: Metrics collector (defaults to global)
        config: Instrumentor configuration

    Example:
        ```python
        # Instrument everything with defaults
        instrument_all()

        # Or with custom config
        instrument_all(config=InstrumentorConfig(
            record_inputs=True,
            record_outputs=True,
        ))
        ```
    """
    global _instrumentors

    instrumentor_classes = [
        ("agent", AgentInstrumentor),
        ("tool", ToolInstrumentor),
        ("llm", LLMInstrumentor),
        ("rag", RAGInstrumentor),
        ("http", HTTPInstrumentor),
    ]

    for name, cls in instrumentor_classes:
        if name not in _instrumentors:
            _instrumentors[name] = cls(tracer=tracer, metrics=metrics, config=config)
        _instrumentors[name].instrument()


def uninstrument_all() -> None:
    """
    Remove all instrumentation.

    Removes instrumentation from all components that were
    instrumented via instrument_all().

    Example:
        ```python
        # During shutdown or for testing
        uninstrument_all()
        ```
    """
    global _instrumentors

    for instrumentor in _instrumentors.values():
        instrumentor.uninstrument()

    _instrumentors.clear()


def get_instrumentor(name: str) -> BaseInstrumentor | None:
    """
    Get a specific instrumentor by name.

    Args:
        name: Instrumentor name (agent, tool, llm, rag, http)

    Returns:
        The instrumentor or None if not found

    Example:
        ```python
        agent_instrumentor = get_instrumentor("agent")
        if agent_instrumentor and agent_instrumentor.is_instrumented:
            print("Agents are instrumented")
        ```
    """
    return _instrumentors.get(name)
