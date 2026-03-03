"""Correlation ID middleware."""
from __future__ import annotations
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get("X-Correlation-ID")
        if raw:
            try:
                uuid.UUID(raw)
                correlation_id = raw
            except ValueError:
                correlation_id = str(uuid.uuid4())
        else:
            correlation_id = str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
