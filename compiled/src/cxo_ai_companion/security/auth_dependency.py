"""FastAPI dependency for extracting authenticated user from Bearer token.

Usage in routes::

    from cxo_ai_companion.security.auth_dependency import get_current_user

    @router.get("/me")
    async def get_me(ctx: SecurityContext = Depends(get_current_user)):
        return {"user_id": ctx.user_id, "email": ctx.metadata.get("email")}

For optional auth (public routes that benefit from user context when
available)::

    @router.get("/items")
    async def list_items(ctx: SecurityContext = Depends(get_optional_user)):
        ...
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cxo_ai_companion.config import Settings
from cxo_ai_companion.dependencies import get_settings
from cxo_ai_companion.security.context import (
    ContextType,
    Permission,
    SecurityContext,
    create_anonymous_context,
)
from cxo_ai_companion.security.jwt_validator import JWTValidator, TokenClaims

import jwt as pyjwt

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=True)
_bearer_scheme_optional = HTTPBearer(auto_error=False)

# Module-level singleton — initialised lazily on first request.
_validator: JWTValidator | None = None


def _get_validator(settings: Settings) -> JWTValidator:
    """Return the module-level ``JWTValidator`` singleton, creating it on first call.

    Args:
        settings: Application settings containing Entra ID configuration.

    Returns:
        The lazily-initialized :class:`JWTValidator`.
    """
    global _validator
    if _validator is None:
        _validator = JWTValidator(
            tenant_id=settings.AZURE_TENANT_ID,
            client_id=settings.AZURE_CLIENT_ID,
            issuer=settings.AZURE_ISSUER or None,
            jwks_uri=settings.AZURE_JWKS_URI or None,
        )
    return _validator


# ── Role → permission mapping ─────────────────────────────────────────────
# Entra ID app roles are mapped to internal RBAC permissions.

_ROLE_PERMISSION_MAP: dict[str, list[str]] = {
    "CXO.Admin": [
        "meetings.*",
        "documents.*",
        "insights.*",
        "notifications.*",
        "projects.*",
        "search.*",
        "admin.*",
    ],
    "CXO.User": [
        "meetings.read",
        "meetings.write",
        "documents.read",
        "documents.write",
        "insights.read",
        "notifications.read",
        "notifications.write",
        "projects.read",
        "projects.write",
        "search.read",
    ],
    "CXO.Viewer": [
        "meetings.read",
        "documents.read",
        "insights.read",
        "notifications.read",
        "search.read",
    ],
}


def _build_security_context(claims: TokenClaims) -> SecurityContext:
    """Convert validated JWT claims into a SecurityContext.

    Maps Entra ID app roles to internal RBAC permissions via
    ``_ROLE_PERMISSION_MAP``. Falls back to ``CXO.User`` permissions
    when no roles are assigned.

    Args:
        claims: Validated token claims from :class:`JWTValidator`.

    Returns:
        A fully populated :class:`SecurityContext`.
    """
    permission_strings: list[str] = []
    for role in claims.roles:
        permission_strings.extend(_ROLE_PERMISSION_MAP.get(role, []))

    # If no Entra roles are assigned, grant default user permissions.
    if not permission_strings:
        permission_strings = list(_ROLE_PERMISSION_MAP["CXO.User"])

    permissions = frozenset(Permission.from_string(p) for p in permission_strings)

    return SecurityContext(
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        context_type=ContextType.USER,
        permissions=permissions,
        roles=frozenset(claims.roles) if claims.roles else frozenset({"CXO.User"}),
        metadata={
            "name": claims.name,
            "email": claims.email,
            "scopes": claims.scopes,
            "auth_method": "entra_id_delegated",
        },
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme_optional),
    settings: Settings = Depends(get_settings),
) -> SecurityContext:
    """FastAPI dependency — returns an authenticated SecurityContext.

    Raises ``401`` if the token is missing or invalid.
    """
    if credentials is None:
        if not settings.REQUIRE_AUTH:
            return create_anonymous_context(
                correlation_id=getattr(request.state, "correlation_id", None),
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        validator = _get_validator(settings)
        claims = await validator.validate_token(credentials.credentials)
        ctx = _build_security_context(claims)
        correlation_id = getattr(request.state, "correlation_id", None)
        if correlation_id:
            ctx = ctx.with_correlation_id(correlation_id)
        return ctx
    except pyjwt.ExpiredSignatureError as exc:
        logger.warning("JWT expired: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except pyjwt.InvalidAudienceError as exc:
        logger.warning("JWT invalid audience: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except pyjwt.InvalidIssuerError as exc:
        logger.warning("JWT invalid issuer: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except pyjwt.InvalidTokenError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme_optional),
    settings: Settings = Depends(get_settings),
) -> SecurityContext:
    """FastAPI dependency -- returns SecurityContext or anonymous if no token."""
    if credentials is None:
        return create_anonymous_context(
            correlation_id=getattr(request.state, "correlation_id", None),
        )
    try:
        validator = _get_validator(settings)
        claims = await validator.validate_token(credentials.credentials)
        return _build_security_context(claims)
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidAudienceError, pyjwt.InvalidIssuerError, pyjwt.InvalidTokenError):
        return create_anonymous_context(
            correlation_id=getattr(request.state, "correlation_id", None),
        )
