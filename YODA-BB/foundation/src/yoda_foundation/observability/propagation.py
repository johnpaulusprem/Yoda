"""
Context propagation for the Agentic AI Component Library.

This module provides propagators for passing trace context between services
following W3C Trace Context and Baggage specifications.

Example:
    ```python
    from yoda_foundation.observability import (
        TraceContextPropagator,
        BaggagePropagator,
        CompositePropagator,
    )

    # Create propagator
    propagator = CompositePropagator([
        TraceContextPropagator(),
        BaggagePropagator(),
    ])

    # Inject context into outgoing request headers
    headers = {}
    propagator.inject(headers)
    await http_client.post(url, headers=headers)

    # Extract context from incoming request
    context = propagator.extract(request.headers)
    # Use context to continue the trace
    ```
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from yoda_foundation.observability.spans import SpanContext


# Try to import OpenTelemetry propagators
_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.baggage.propagation import W3CBaggagePropagator
    from opentelemetry.propagate import extract, inject, set_global_textmap
    from opentelemetry.propagators.composite import CompositePropagator as OtelCompositePropagator
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    _OTEL_AVAILABLE = True
except ImportError:
    otel_trace = None
    inject = None
    extract = None
    set_global_textmap = None
    OtelCompositePropagator = None
    TraceContextTextMapPropagator = None
    W3CBaggagePropagator = None


class Propagator(ABC):
    """
    Abstract base class for context propagators.

    Propagators are responsible for injecting and extracting trace context
    from carriers (typically HTTP headers or message attributes).

    Example:
        ```python
        class CustomPropagator(Propagator):
            def inject(self, carrier: Dict[str, str]) -> Dict[str, str]:
                # Add custom headers
                carrier["X-Custom-Trace"] = get_trace_id()
                return carrier

            def extract(self, carrier: Dict[str, str]) -> Optional[SpanContext]:
                # Extract from custom headers
                trace_id = carrier.get("X-Custom-Trace")
                if trace_id:
                    return SpanContext(trace_id=trace_id, span_id="0000")
                return None
        ```
    """

    @abstractmethod
    def inject(self, carrier: dict[str, str]) -> dict[str, str]:
        """
        Inject trace context into a carrier.

        Args:
            carrier: Dictionary to inject context into (usually headers)

        Returns:
            The carrier with injected context
        """
        pass

    @abstractmethod
    def extract(self, carrier: dict[str, str]) -> SpanContext | None:
        """
        Extract trace context from a carrier.

        Args:
            carrier: Dictionary containing context (usually headers)

        Returns:
            Extracted SpanContext or None if not found
        """
        pass

    @property
    @abstractmethod
    def fields(self) -> list[str]:
        """
        Get the header/field names used by this propagator.

        Returns:
            List of field names
        """
        pass


class TraceContextPropagator(Propagator):
    """
    W3C Trace Context propagator.

    Implements the W3C Trace Context specification for distributed tracing.
    Uses 'traceparent' and 'tracestate' headers.

    Format:
        traceparent: {version}-{trace_id}-{span_id}-{flags}
        tracestate: {key}={value},{key}={value},...

    Example:
        ```python
        propagator = TraceContextPropagator()

        # Inject into outgoing headers
        headers = {}
        propagator.inject(headers)
        # headers = {"traceparent": "00-abc123...-def456...-01"}

        # Extract from incoming headers
        context = propagator.extract(request.headers)
        if context:
            print(f"Trace ID: {context.trace_id}")
        ```
    """

    TRACEPARENT_HEADER = "traceparent"
    TRACESTATE_HEADER = "tracestate"
    VERSION = "00"

    # Regex pattern for traceparent header
    _TRACEPARENT_PATTERN = re.compile(
        r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
    )

    def __init__(self) -> None:
        """Initialize the propagator."""
        self._otel_propagator = None
        if _OTEL_AVAILABLE:
            self._otel_propagator = TraceContextTextMapPropagator()

    def inject(self, carrier: dict[str, str]) -> dict[str, str]:
        """
        Inject W3C Trace Context into carrier.

        Args:
            carrier: Dictionary to inject context into

        Returns:
            The carrier with traceparent/tracestate headers

        Example:
            ```python
            headers = {}
            propagator.inject(headers)
            # headers now contains traceparent header
            ```
        """
        if _OTEL_AVAILABLE and self._otel_propagator:
            inject(carrier)
            return carrier

        # Fallback: Get current span context from NoOp tracer
        from yoda_foundation.observability.tracer import get_tracer

        tracer = get_tracer()
        span = tracer.current_span()

        if span is not None:
            ctx = span.get_span_context()
            if hasattr(ctx, "trace_id"):
                # Format traceparent
                trace_id = (
                    ctx.trace_id if isinstance(ctx.trace_id, str) else format(ctx.trace_id, "032x")
                )
                span_id = (
                    ctx.span_id if isinstance(ctx.span_id, str) else format(ctx.span_id, "016x")
                )
                flags = format(ctx.trace_flags, "02x")

                carrier[self.TRACEPARENT_HEADER] = f"{self.VERSION}-{trace_id}-{span_id}-{flags}"

                if ctx.trace_state:
                    carrier[self.TRACESTATE_HEADER] = ctx.trace_state

        return carrier

    def extract(self, carrier: dict[str, str]) -> SpanContext | None:
        """
        Extract W3C Trace Context from carrier.

        Args:
            carrier: Dictionary containing trace context

        Returns:
            Extracted SpanContext or None

        Example:
            ```python
            context = propagator.extract(request.headers)
            if context:
                # Continue the trace
                async with tracer.async_span("handle", parent=context) as span:
                    await process()
            ```
        """
        # Get traceparent header (case-insensitive)
        traceparent = None
        tracestate = None

        for key, value in carrier.items():
            key_lower = key.lower()
            if key_lower == self.TRACEPARENT_HEADER:
                traceparent = value
            elif key_lower == self.TRACESTATE_HEADER:
                tracestate = value

        if not traceparent:
            return None

        # Parse traceparent
        match = self._TRACEPARENT_PATTERN.match(traceparent.strip())
        if not match:
            return None

        version, trace_id, span_id, flags = match.groups()

        # Validate version
        if version != self.VERSION:
            # Unknown version - still try to parse
            pass

        # Validate trace_id and span_id are not all zeros
        if trace_id == "0" * 32 or span_id == "0" * 16:
            return None

        return SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            trace_flags=int(flags, 16),
            trace_state=tracestate,
            is_remote=True,
        )

    @property
    def fields(self) -> list[str]:
        """Get the header names used by this propagator."""
        return [self.TRACEPARENT_HEADER, self.TRACESTATE_HEADER]


@dataclass
class BaggageItem:
    """A single baggage item."""

    key: str
    value: str
    metadata: str | None = None


class BaggagePropagator(Propagator):
    """
    W3C Baggage propagator.

    Propagates baggage (key-value pairs) across service boundaries.
    Useful for passing business context like user IDs, tenant IDs, etc.

    Format:
        baggage: key1=value1,key2=value2;metadata

    Example:
        ```python
        propagator = BaggagePropagator()

        # Set baggage
        propagator.set_baggage("user_id", "user_123")
        propagator.set_baggage("tenant_id", "tenant_456")

        # Inject into headers
        headers = {}
        propagator.inject(headers)
        # headers = {"baggage": "user_id=user_123,tenant_id=tenant_456"}

        # Extract from headers
        context = propagator.extract(request.headers)
        items = propagator.get_baggage_items(request.headers)
        ```
    """

    BAGGAGE_HEADER = "baggage"

    def __init__(self) -> None:
        """Initialize the propagator."""
        self._baggage: dict[str, BaggageItem] = {}
        self._otel_propagator = None
        if _OTEL_AVAILABLE:
            self._otel_propagator = W3CBaggagePropagator()

    def set_baggage(
        self,
        key: str,
        value: str,
        metadata: str | None = None,
    ) -> None:
        """
        Set a baggage item.

        Args:
            key: Baggage key
            value: Baggage value
            metadata: Optional metadata

        Example:
            ```python
            propagator.set_baggage("user_id", "user_123")
            propagator.set_baggage("feature_flags", "dark_mode=true", metadata="priority=low")
            ```
        """
        self._baggage[key] = BaggageItem(key=key, value=value, metadata=metadata)

    def get_baggage(self, key: str) -> str | None:
        """
        Get a baggage value.

        Args:
            key: Baggage key

        Returns:
            Baggage value or None

        Example:
            ```python
            user_id = propagator.get_baggage("user_id")
            ```
        """
        item = self._baggage.get(key)
        return item.value if item else None

    def remove_baggage(self, key: str) -> None:
        """
        Remove a baggage item.

        Args:
            key: Baggage key

        Example:
            ```python
            propagator.remove_baggage("temp_data")
            ```
        """
        self._baggage.pop(key, None)

    def clear_baggage(self) -> None:
        """
        Clear all baggage items.

        Example:
            ```python
            propagator.clear_baggage()
            ```
        """
        self._baggage.clear()

    def inject(self, carrier: dict[str, str]) -> dict[str, str]:
        """
        Inject baggage into carrier.

        Args:
            carrier: Dictionary to inject baggage into

        Returns:
            The carrier with baggage header

        Example:
            ```python
            propagator.set_baggage("user_id", "user_123")
            headers = {}
            propagator.inject(headers)
            ```
        """
        if _OTEL_AVAILABLE and self._otel_propagator:
            inject(carrier)
            return carrier

        if not self._baggage:
            return carrier

        # Format baggage header
        items = []
        for item in self._baggage.values():
            # URL-encode special characters
            encoded_key = self._encode(item.key)
            encoded_value = self._encode(item.value)

            entry = f"{encoded_key}={encoded_value}"
            if item.metadata:
                entry += f";{item.metadata}"

            items.append(entry)

        carrier[self.BAGGAGE_HEADER] = ",".join(items)
        return carrier

    def extract(self, carrier: dict[str, str]) -> SpanContext | None:
        """
        Extract baggage from carrier.

        Note: This propagator doesn't extract SpanContext, only baggage.
        Returns None. Use get_baggage_items() to get extracted baggage.

        Args:
            carrier: Dictionary containing baggage

        Returns:
            None (use get_baggage_items instead)
        """
        # Parse baggage and store internally
        self._parse_baggage(carrier)
        return None

    def get_baggage_items(self, carrier: dict[str, str]) -> dict[str, str]:
        """
        Get baggage items from carrier.

        Args:
            carrier: Dictionary containing baggage header

        Returns:
            Dictionary of baggage key-value pairs

        Example:
            ```python
            items = propagator.get_baggage_items(request.headers)
            user_id = items.get("user_id")
            ```
        """
        self._parse_baggage(carrier)
        return {k: v.value for k, v in self._baggage.items()}

    def _parse_baggage(self, carrier: dict[str, str]) -> None:
        """Parse baggage from carrier."""
        # Get baggage header (case-insensitive)
        baggage = None
        for key, value in carrier.items():
            if key.lower() == self.BAGGAGE_HEADER:
                baggage = value
                break

        if not baggage:
            return

        # Parse entries
        for entry in baggage.split(","):
            entry = entry.strip()
            if not entry:
                continue

            # Split by semicolon for metadata
            parts = entry.split(";", 1)
            kv_part = parts[0]
            metadata = parts[1] if len(parts) > 1 else None

            # Split key=value
            if "=" in kv_part:
                key, value = kv_part.split("=", 1)
                key = self._decode(key.strip())
                value = self._decode(value.strip())

                self._baggage[key] = BaggageItem(
                    key=key,
                    value=value,
                    metadata=metadata,
                )

    def _encode(self, value: str) -> str:
        """URL-encode a value for baggage."""
        # Simple encoding for special characters
        return value.replace("%", "%25").replace(",", "%2C").replace(";", "%3B").replace("=", "%3D")

    def _decode(self, value: str) -> str:
        """URL-decode a baggage value."""
        return value.replace("%3D", "=").replace("%3B", ";").replace("%2C", ",").replace("%25", "%")

    @property
    def fields(self) -> list[str]:
        """Get the header names used by this propagator."""
        return [self.BAGGAGE_HEADER]


class CompositePropagator(Propagator):
    """
    Composite propagator that combines multiple propagators.

    Useful for supporting multiple propagation formats simultaneously.

    Example:
        ```python
        propagator = CompositePropagator([
            TraceContextPropagator(),
            BaggagePropagator(),
        ])

        # Inject using all propagators
        headers = {}
        propagator.inject(headers)
        # headers contains traceparent, tracestate, and baggage

        # Extract tries each propagator
        context = propagator.extract(request.headers)
        ```
    """

    def __init__(self, propagators: list[Propagator] | None = None) -> None:
        """
        Initialize the composite propagator.

        Args:
            propagators: List of propagators to combine

        Example:
            ```python
            propagator = CompositePropagator([
                TraceContextPropagator(),
                BaggagePropagator(),
            ])
            ```
        """
        self._propagators = propagators or [
            TraceContextPropagator(),
            BaggagePropagator(),
        ]

    def inject(self, carrier: dict[str, str]) -> dict[str, str]:
        """
        Inject context using all propagators.

        Args:
            carrier: Dictionary to inject context into

        Returns:
            The carrier with injected context

        Example:
            ```python
            headers = {}
            propagator.inject(headers)
            ```
        """
        for propagator in self._propagators:
            propagator.inject(carrier)
        return carrier

    def extract(self, carrier: dict[str, str]) -> SpanContext | None:
        """
        Extract context using the first successful propagator.

        Args:
            carrier: Dictionary containing context

        Returns:
            Extracted SpanContext or None

        Example:
            ```python
            context = propagator.extract(request.headers)
            ```
        """
        for propagator in self._propagators:
            context = propagator.extract(carrier)
            if context is not None:
                return context
        return None

    @property
    def fields(self) -> list[str]:
        """Get all header names used by the propagators."""
        all_fields = []
        for propagator in self._propagators:
            all_fields.extend(propagator.fields)
        return list(set(all_fields))

    def add_propagator(self, propagator: Propagator) -> None:
        """
        Add a propagator to the composite.

        Args:
            propagator: Propagator to add

        Example:
            ```python
            composite.add_propagator(CustomPropagator())
            ```
        """
        self._propagators.append(propagator)


# Global propagator
_global_propagator: CompositePropagator | None = None


def get_propagator() -> CompositePropagator:
    """
    Get the global propagator instance.

    Returns:
        The global CompositePropagator instance

    Example:
        ```python
        propagator = get_propagator()
        propagator.inject(headers)
        ```
    """
    global _global_propagator
    if _global_propagator is None:
        _global_propagator = CompositePropagator()
    return _global_propagator


def set_propagator(propagator: CompositePropagator) -> None:
    """
    Set the global propagator instance.

    Args:
        propagator: The propagator to set as global

    Example:
        ```python
        propagator = CompositePropagator([
            TraceContextPropagator(),
            BaggagePropagator(),
        ])
        set_propagator(propagator)
        ```
    """
    global _global_propagator
    _global_propagator = propagator


def inject_context(carrier: dict[str, str]) -> dict[str, str]:
    """
    Inject trace context into a carrier using the global propagator.

    Args:
        carrier: Dictionary to inject context into

    Returns:
        The carrier with injected context

    Example:
        ```python
        headers = {}
        inject_context(headers)
        await http_client.post(url, headers=headers)
        ```
    """
    return get_propagator().inject(carrier)


def extract_context(carrier: dict[str, str]) -> SpanContext | None:
    """
    Extract trace context from a carrier using the global propagator.

    Args:
        carrier: Dictionary containing context

    Returns:
        Extracted SpanContext or None

    Example:
        ```python
        context = extract_context(request.headers)
        if context:
            async with tracer.async_span("handle", parent=context) as span:
                await process_request()
        ```
    """
    return get_propagator().extract(carrier)
