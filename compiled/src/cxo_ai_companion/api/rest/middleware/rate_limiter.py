"""In-memory token-bucket rate limiter middleware."""
from __future__ import annotations

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter keyed by client IP."""

    def __init__(self, app, rpm: int = 100, burst: int = 20):
        super().__init__(app)
        self._rpm = rpm
        self._burst = burst
        self._buckets: dict[str, dict] = defaultdict(lambda: {"tokens": burst, "last": time.monotonic()})

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ("/health", "/metrics"):
            return await call_next(request)

        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.client.host if request.client else "unknown"
        bucket = self._buckets[client_ip]
        now = time.monotonic()
        elapsed = now - bucket["last"]
        bucket["last"] = now

        # Refill tokens
        refill = elapsed * (self._rpm / 60.0)
        bucket["tokens"] = min(self._burst, bucket["tokens"] + refill)

        if bucket["tokens"] < 1:
            retry_after = int(60 / self._rpm) or 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

        bucket["tokens"] -= 1
        return await call_next(request)
