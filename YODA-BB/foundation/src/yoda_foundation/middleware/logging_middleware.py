"""Request/response logging middleware."""
from __future__ import annotations
import logging, time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("yoda_foundation.api")

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/metrics"):
            return await call_next(request)
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info("HTTP %s %s %d %.1fms", request.method, request.url.path, response.status_code, duration_ms, extra={"method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": round(duration_ms, 1), "correlation_id": getattr(request.state, "correlation_id", None)})
        return response
