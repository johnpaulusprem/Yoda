"""Structured JSON logging setup for the meeting service.

Configures python-json-logger so all log output is machine-parseable JSON,
compatible with Azure Monitor ingestion. Third-party loggers (httpx, httpcore,
azure) are throttled to WARNING to reduce noise in production.
"""

import logging
import sys

from pythonjsonlogger import jsonlogger


def setup_logging(debug: bool = False) -> None:
    """Configure structured JSON logging for Azure Monitor compatibility."""
    log_level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("azure").setLevel(logging.WARNING)
