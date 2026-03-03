"""JWT token validation for Microsoft Entra ID (delegated flow).

Validates access tokens issued by Entra ID when users sign in via the React
frontend.  The validator downloads Microsoft's public signing keys (JWKS) and
verifies the JWT signature, expiry, audience, and issuer before extracting
user identity claims.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
import jwt  # PyJWT
from jwt import PyJWKClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenClaims:
    """Decoded claims extracted from a validated Entra ID JWT.

    Attributes:
        user_id: The user's object ID in Entra ID (``oid`` claim).
        tenant_id: The Azure AD tenant (``tid`` claim).
        name: Display name (``name`` claim).
        email: User principal name or email (``preferred_username`` / ``upn``).
        roles: App roles assigned to the user (``roles`` claim).
        scopes: Delegated scopes granted (``scp`` claim, space-separated).
    """

    user_id: str
    tenant_id: str
    name: str
    email: str
    roles: list[str]
    scopes: list[str]


class JWTValidator:
    """Validate Entra ID JWT access tokens.

    Downloads Microsoft's public signing keys (JWKS), verifies the JWT
    signature, expiry, audience, and issuer, then extracts user claims.

    Args:
        tenant_id: Azure AD / Entra ID tenant identifier.
        client_id: Application (client) ID -- used as the expected ``aud`` claim.
        issuer: Expected ``iss`` claim. Defaults to the v2.0 issuer URL.
        jwks_uri: URI for Microsoft's JSON Web Key Set. Defaults to the v2.0 endpoint.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        *,
        issuer: str | None = None,
        jwks_uri: str | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._issuer = (
            issuer
            or f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        )
        self._jwks_uri = (
            jwks_uri
            or f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )
        self._jwk_client = PyJWKClient(self._jwks_uri, cache_keys=True)

    async def validate_token(self, token: str) -> TokenClaims:
        """Validate a Bearer token and return the extracted claims.

        Args:
            token: The raw JWT access token string.

        Returns:
            A :class:`TokenClaims` with decoded user identity and roles.

        Raises:
            jwt.InvalidTokenError: If the token is invalid, expired, or has
                an incorrect audience / issuer.
        """
        signing_key = self._jwk_client.get_signing_key_from_jwt(token)

        payload: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self._client_id,
            issuer=self._issuer,
            options={
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )

        # Extract claims — handle both v1 and v2 token formats.
        user_id = payload.get("oid") or payload.get("sub", "")
        tenant_id = payload.get("tid", self._tenant_id)
        name = payload.get("name", "")
        email = (
            payload.get("preferred_username")
            or payload.get("upn")
            or payload.get("email", "")
        )

        # 'roles' is a list when app roles are assigned; absent otherwise.
        roles: list[str] = payload.get("roles", [])

        # 'scp' (scope) is a space-separated string for delegated tokens.
        scp_raw = payload.get("scp", "")
        scopes = scp_raw.split() if isinstance(scp_raw, str) else []

        logger.debug(
            "JWT validated: user_id=%s tenant=%s email=%s",
            user_id,
            tenant_id,
            email,
        )

        return TokenClaims(
            user_id=user_id,
            tenant_id=tenant_id,
            name=name,
            email=email,
            roles=roles,
            scopes=scopes,
        )
