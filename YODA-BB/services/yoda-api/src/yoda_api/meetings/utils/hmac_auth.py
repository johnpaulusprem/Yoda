"""HMAC-SHA256 request validation for inter-service communication."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from cachetools import TTLCache
from fastapi import HTTPException, Request

from yoda_api.config import Settings

logger = logging.getLogger(__name__)

# Maximum allowed clock drift between services (seconds)
_MAX_TIMESTAMP_DRIFT = 60

# Nonce cache: stores seen nonces for TTL seconds to prevent replay attacks.
_seen_nonces: TTLCache[str, bool] = TTLCache(maxsize=10_000, ttl=_MAX_TIMESTAMP_DRIFT)


async def validate_hmac(request: Request, settings: Settings) -> None:
    """Validate HMAC signature on incoming requests from the Browser Bot.

    Raises HTTPException(401) on validation failure.
    Skips validation entirely if INTER_SERVICE_HMAC_KEY is not configured (dev mode).
    """
    if not settings.INTER_SERVICE_HMAC_KEY:
        if getattr(settings, "DEBUG", False) is False:
            logger.warning(
                "HMAC validation skipped — INTER_SERVICE_HMAC_KEY not set. "
                "This is acceptable only in development."
            )
        return

    timestamp = request.headers.get("X-Request-Timestamp", "")
    signature = request.headers.get("X-Request-Signature", "")
    nonce = request.headers.get("X-Request-Nonce", "")
    if not timestamp or not signature:
        logger.warning(
            "HMAC validation failed: missing headers for %s %s",
            request.method,
            request.url.path,
        )
        raise HTTPException(status_code=401, detail="Missing HMAC headers")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        logger.warning("HMAC validation failed: non-integer timestamp")
        raise HTTPException(status_code=401, detail="Invalid timestamp") from exc

    drift = abs(time.time() - ts)
    if drift > _MAX_TIMESTAMP_DRIFT:
        logger.warning(
            "HMAC validation failed: timestamp drift %.0fs exceeds %ds for %s %s",
            drift,
            _MAX_TIMESTAMP_DRIFT,
            request.method,
            request.url.path,
        )
        raise HTTPException(status_code=401, detail="Request expired")

    # Nonce replay protection
    if nonce:
        if nonce in _seen_nonces:
            logger.warning(
                "HMAC validation failed: replayed nonce for %s %s",
                request.method,
                request.url.path,
            )
            raise HTTPException(status_code=401, detail="Replayed request")
        _seen_nonces[nonce] = True

    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest()
    method = request.method
    path = request.url.path
    # Include nonce in payload (backwards compatible — empty string if no nonce)
    payload = f"{timestamp}{nonce}{method}{path}{body_hash}"

    expected = hmac.new(
        settings.INTER_SERVICE_HMAC_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        logger.warning(
            "HMAC validation failed: invalid signature for %s %s",
            request.method,
            request.url.path,
        )
        raise HTTPException(status_code=401, detail="Invalid signature")
