"""Azure AD JWT Bearer token validation for API routes."""
from __future__ import annotations

import logging
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from yoda_api.config import Settings

logger = logging.getLogger(__name__)
_bearer_scheme = HTTPBearer(auto_error=False)

_jwks_cache: dict | None = None


async def _get_jwks(tenant_id: str) -> dict:
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        return _jwks_cache


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """Validate Azure AD JWT and return decoded claims.

    Skips validation if AZURE_AD_AUDIENCE is not configured (dev mode).
    """
    settings = _get_settings(request)

    if not settings.AZURE_AD_AUDIENCE:
        return {"sub": "dev-user", "name": "Developer", "roles": ["Admin"]}

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = credentials.credentials
    try:
        jwks = await _get_jwks(settings.AZURE_TENANT_ID)
        from jwt.api_jwk import PyJWKSet
        jwk_set = PyJWKSet.from_dict(jwks)

        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        signing_key = None
        for key in jwk_set.keys:
            if key.key_id == kid:
                signing_key = key
                break

        if signing_key is None:
            raise HTTPException(status_code=401, detail="Unable to find signing key")

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.AZURE_AD_AUDIENCE,
            issuer=f"https://login.microsoftonline.com/{settings.AZURE_TENANT_ID}/v2.0",
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_admin(
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """Require the Admin role claim."""
    settings = _get_settings(request)
    roles = user.get("roles", [])
    if settings.AZURE_AD_ADMIN_ROLE not in roles:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
