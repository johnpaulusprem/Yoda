"""OpenTelemetry setup for Azure Application Insights."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def setup_telemetry(app) -> None:
    """Instrument FastAPI with OpenTelemetry + Azure Monitor exporter.

    No-op if APPLICATIONINSIGHTS_CONNECTION_STRING is not set.
    """
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        logger.info("APPLICATIONINSIGHTS_CONNECTION_STRING not set — telemetry disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        provider = TracerProvider()
        exporter = AzureMonitorTraceExporter(connection_string=connection_string)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry + Azure Monitor configured")
    except ImportError:
        logger.warning("OpenTelemetry packages not installed — telemetry disabled")
