"""Metrics collection with OpenTelemetry graceful degradation."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class NoOpCounter:
    def add(self, value: int = 1, attributes: dict[str, Any] | None = None) -> None:
        pass

class NoOpHistogram:
    def record(self, value: float, attributes: dict[str, Any] | None = None) -> None:
        pass

class NoOpGauge:
    def set(self, value: float, attributes: dict[str, Any] | None = None) -> None:
        pass


class CXOMetrics:
    """Pre-defined metrics for the CXO AI Companion."""

    def __init__(self, service_name: str = "cxo-ai-companion") -> None:
        self._service_name = service_name
        self._enabled = False

        try:
            from opentelemetry import metrics
            from opentelemetry.sdk.metrics import MeterProvider
            provider = MeterProvider()
            metrics.set_meter_provider(provider)
            meter = metrics.get_meter(service_name)

            self.meetings_processed = meter.create_counter("meetings_processed", description="Total meetings processed")
            self.transcription_segments = meter.create_counter("transcription_segments", description="Total transcript segments")
            self.ai_processing_duration = meter.create_histogram("ai_processing_duration_seconds", description="AI processing duration")
            self.action_items_created = meter.create_counter("action_items_created", description="Total action items created")
            self.delivery_success = meter.create_counter("delivery_success", description="Successful deliveries")
            self.delivery_failure = meter.create_counter("delivery_failure", description="Failed deliveries")
            self.cache_hits = meter.create_counter("cache_hits", description="Cache hits")
            self.cache_misses = meter.create_counter("cache_misses", description="Cache misses")
            self.http_requests = meter.create_counter("http_requests_total", description="Total HTTP requests")
            self.http_duration = meter.create_histogram("http_request_duration_seconds", description="HTTP request duration")
            self.active_meetings = meter.create_up_down_counter("active_meetings", description="Currently active meetings")
            self._enabled = True
            logger.info("OpenTelemetry metrics enabled for %s", service_name)
        except ImportError:
            logger.info("OpenTelemetry not installed — metrics disabled, using no-op")
            self.meetings_processed = NoOpCounter()
            self.transcription_segments = NoOpCounter()
            self.ai_processing_duration = NoOpHistogram()
            self.action_items_created = NoOpCounter()
            self.delivery_success = NoOpCounter()
            self.delivery_failure = NoOpCounter()
            self.cache_hits = NoOpCounter()
            self.cache_misses = NoOpCounter()
            self.http_requests = NoOpCounter()
            self.http_duration = NoOpHistogram()
            self.active_meetings = NoOpCounter()

    def record_meeting_processed(self, model: str, duration_seconds: float, action_items: int) -> None:
        self.meetings_processed.add(1, {"model": model})
        self.ai_processing_duration.record(duration_seconds, {"model": model})
        self.action_items_created.add(action_items)

    def record_http_request(self, method: str, path: str, status_code: int, duration: float) -> None:
        attrs = {"method": method, "path": path, "status_code": status_code}
        self.http_requests.add(1, attrs)
        self.http_duration.record(duration, attrs)


_global_metrics: CXOMetrics | None = None

def get_metrics() -> CXOMetrics:
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = CXOMetrics()
    return _global_metrics

def set_metrics(metrics: CXOMetrics) -> None:
    global _global_metrics
    _global_metrics = metrics
