"""Exception handler middleware for FastAPI."""
from __future__ import annotations
import logging, uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from fastapi import HTTPException
from yoda_foundation.exceptions.base import YodaBaseException, ErrorSeverity

logger = logging.getLogger(__name__)

class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
        try:
            return await call_next(request)
        except YodaBaseException as exc:
            log_method = logger.error if exc.severity in (ErrorSeverity.HIGH, ErrorSeverity.CRITICAL) else logger.warning
            log_method("CXO error: %s", exc, extra=exc.to_log_dict())
            status_map = {"authentication": 401, "authorization": 403, "validation": 422, "rate_limit": 429}
            status = status_map.get(exc.category.value, 500)
            body = exc.to_dict(); body["error"]["correlation_id"] = correlation_id
            return JSONResponse(status_code=status, content=body)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"error": {"message": exc.detail, "correlation_id": correlation_id}})
        except Exception as exc:
            logger.exception("Unhandled error: %s", exc)
            return JSONResponse(status_code=500, content={"error": {"message": "Internal server error", "correlation_id": correlation_id}})
