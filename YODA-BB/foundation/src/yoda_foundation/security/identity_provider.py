"""
Identity provider abstractions for the Agentic AI Component Library.

This module provides pluggable identity provider integrations for
enterprise SSO, OAuth, SAML, and API key authentication.

Example:
    ```python
    from yoda_foundation.security import (
        OAuthProvider,
        SAMLProvider,
        APIKeyProvider,
    )

    # Configure OAuth provider
    oauth = OAuthProvider(
        provider_name="google",
        client_id="your_client_id",
        client_secret="your_client_secret",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
    )

    # Authenticate user
    identity = await oauth.authenticate(authorization_code="code123")

    # Validate and refresh token
    if await oauth.validate_token(access_token):
        new_token = await oauth.refresh_token(refresh_token)
    ```
"""

from __future__ import annotations

import hashlib
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from yoda_foundation.security.user_identity import CredentialType, UserIdentity


class ProviderType(Enum):
    """Type of identity provider."""

    OAUTH = "oauth"
    SAML = "saml"
    OIDC = "oidc"
    LDAP = "ldap"
    API_KEY = "api_key"
    CUSTOM = "custom"


@dataclass
class TokenInfo:
    """
    Information about an authentication token.

    Attributes:
        access_token: The access token
        token_type: Token type (e.g., "Bearer")
        expires_in: Seconds until expiration
        refresh_token: Optional refresh token
        scope: Token scope
        issued_at: When the token was issued
        expires_at: When the token expires
        metadata: Additional token metadata

    Example:
        ```python
        token = TokenInfo(
            access_token="eyJhbGciOi.EXAMPLE_TOKEN",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="EXAMPLE_REFRESH_TOKEN",
            scope="openid email profile",
        )

        if token.is_expired():
            # Refresh the token
            new_token = await provider.refresh_token(token.refresh_token)
        ```
    """

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: str | None = None
    scope: str | None = None
    issued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Calculate expiration time if not provided."""
        if self.expires_at is None and self.expires_in:
            self.expires_at = self.issued_at + timedelta(seconds=self.expires_in)

    def is_expired(self) -> bool:
        """
        Check if the token has expired.

        Returns:
            True if the token is expired
        """
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert token info to dictionary."""
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "refresh_token": self.refresh_token,
            "scope": self.scope,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata,
        }


class IdentityProvider(ABC):
    """
    Abstract base class for identity providers.

    Defines the interface that all identity providers must implement
    for authentication, token validation, and user identity retrieval.

    Example:
        ```python
        class CustomProvider(IdentityProvider):
            async def authenticate(
                self,
                credentials: Dict[str, Any],
            ) -> UserIdentity:
                # Custom authentication logic
                user_data = await self._verify_credentials(credentials)
                return self._create_identity(user_data)

            async def validate_token(self, token: str) -> bool:
                # Custom token validation
                return await self._check_token(token)
        ```
    """

    def __init__(
        self,
        provider_name: str,
        provider_type: ProviderType,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize identity provider.

        Args:
            provider_name: Name of the provider
            provider_type: Type of provider
            config: Provider-specific configuration
        """
        self.provider_name = provider_name
        self.provider_type = provider_type
        self.config = config or {}

    @abstractmethod
    async def authenticate(
        self,
        credentials: dict[str, Any],
    ) -> UserIdentity:
        """
        Authenticate a user with the given credentials.

        Args:
            credentials: Authentication credentials (format varies by provider)

        Returns:
            UserIdentity for the authenticated user

        Raises:
            AuthenticationError: If authentication fails
        """
        pass

    @abstractmethod
    async def validate_token(self, token: str) -> bool:
        """
        Validate an authentication token.

        Args:
            token: Token to validate

        Returns:
            True if the token is valid

        Raises:
            AuthenticationError: If validation fails
        """
        pass

    async def refresh_token(self, refresh_token: str) -> TokenInfo | None:
        """
        Refresh an access token using a refresh token.

        Args:
            refresh_token: The refresh token

        Returns:
            New TokenInfo if refresh is supported, None otherwise

        Raises:
            AuthenticationError: If refresh fails

        Note:
            Default implementation returns None. Override in subclasses
            that support token refresh.
        """
        return None

    async def revoke_token(self, token: str) -> bool:
        """
        Revoke an authentication token.

        Args:
            token: Token to revoke

        Returns:
            True if revocation succeeded

        Note:
            Default implementation returns True. Override in subclasses
            that support token revocation.
        """
        return True

    async def get_user_info(self, token: str) -> dict[str, Any] | None:
        """
        Get user information from the identity provider.

        Args:
            token: Valid access token

        Returns:
            User information dictionary if available

        Note:
            Default implementation returns None. Override in subclasses
            that support user info retrieval.
        """
        return None


class OAuthProvider(IdentityProvider):
    """
    OAuth 2.0 identity provider.

    Supports standard OAuth 2.0 flows including authorization code,
    client credentials, and token refresh.

    Attributes:
        client_id: OAuth client ID
        client_secret: OAuth client secret
        authorization_url: Authorization endpoint URL
        token_url: Token endpoint URL
        userinfo_url: User info endpoint URL
        scopes: Default OAuth scopes

    Example:
        ```python
        # Configure Google OAuth
        provider = OAuthProvider(
            provider_name="google",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
            scopes=["openid", "email", "profile"],
        )

        # Get authorization URL
        auth_url = provider.get_authorization_url(
            redirect_uri="https://app.com/callback",
            state="random_state",
        )

        # Exchange code for token
        token = await provider.exchange_code(
            code="auth_code",
            redirect_uri="https://app.com/callback",
        )

        # Get user identity
        identity = await provider.authenticate({
            "access_token": token.access_token,
        })
        ```
    """

    def __init__(
        self,
        provider_name: str,
        client_id: str,
        client_secret: str,
        authorization_url: str,
        token_url: str,
        userinfo_url: str | None = None,
        scopes: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize OAuth provider.

        Args:
            provider_name: Name of the provider (e.g., "google", "github")
            client_id: OAuth client ID
            client_secret: OAuth client secret
            authorization_url: Authorization endpoint URL
            token_url: Token endpoint URL
            userinfo_url: User info endpoint URL
            scopes: Default OAuth scopes
            config: Additional configuration
        """
        super().__init__(provider_name, ProviderType.OAUTH, config)
        self.client_id = client_id
        self.client_secret = client_secret
        self.authorization_url = authorization_url
        self.token_url = token_url
        self.userinfo_url = userinfo_url
        self.scopes = scopes or ["openid", "email", "profile"]

    def get_authorization_url(
        self,
        redirect_uri: str,
        state: str | None = None,
        scopes: list[str] | None = None,
    ) -> str:
        """
        Generate OAuth authorization URL.

        Args:
            redirect_uri: Callback URL
            state: State parameter for CSRF protection
            scopes: OAuth scopes (uses default if not provided)

        Returns:
            Authorization URL

        Example:
            ```python
            auth_url = provider.get_authorization_url(
                redirect_uri="https://app.com/callback",
                state=secrets.token_urlsafe(32),
            )
            # Redirect user to auth_url
            ```
        """
        from urllib.parse import urlencode

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes or self.scopes),
        }

        if state:
            params["state"] = state

        return f"{self.authorization_url}?{urlencode(params)}"

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> TokenInfo:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code
            redirect_uri: Redirect URI used in authorization

        Returns:
            TokenInfo with access and refresh tokens

        Raises:
            AuthenticationError: If token exchange fails

        Example:
            ```python
            # In callback handler
            code = request.args.get("code")
            token = await provider.exchange_code(
                code=code,
                redirect_uri="https://app.com/callback",
            )
            ```

        Note:
            This is a placeholder. In production, make actual HTTP request
            to the token endpoint.
        """
        from yoda_foundation.exceptions import AuthenticationError

        # NOTE: Placeholder implementation
        # In production, make POST request to token_url
        # with client credentials and authorization code

        # Simulate token exchange
        if not code:
            raise AuthenticationError(
                message="Authorization code is required",
                auth_method="oauth",
                reason="missing_code",
            )

        # Return mock token
        return TokenInfo(
            access_token=secrets.token_urlsafe(32),
            token_type="Bearer",
            expires_in=3600,
            refresh_token=secrets.token_urlsafe(32),
            scope=" ".join(self.scopes),
            metadata={
                "provider": self.provider_name,
                "code": code[:10] + "...",
            },
        )

    async def authenticate(
        self,
        credentials: dict[str, Any],
    ) -> UserIdentity:
        """
        Authenticate user with OAuth token.

        Args:
            credentials: Dictionary containing "access_token"

        Returns:
            UserIdentity for the authenticated user

        Raises:
            AuthenticationError: If authentication fails

        Example:
            ```python
            identity = await provider.authenticate({
                "access_token": "eyJhbGciOi.EXAMPLE_TOKEN",
            })
            ```
        """
        from yoda_foundation.exceptions import AuthenticationError

        access_token = credentials.get("access_token")
        if not access_token:
            raise AuthenticationError(
                message="Access token is required",
                auth_method="oauth",
                reason="missing_token",
            )

        # Validate token
        if not await self.validate_token(access_token):
            raise AuthenticationError(
                message="Invalid access token",
                auth_method="oauth",
                reason="invalid_token",
            )

        # Get user info
        user_info = await self.get_user_info(access_token)
        if not user_info:
            raise AuthenticationError(
                message="Failed to retrieve user information",
                auth_method="oauth",
                reason="userinfo_failed",
            )

        # Create identity
        return UserIdentity(
            user_id=user_info.get("sub", user_info.get("id", "")),
            username=user_info.get("preferred_username", user_info.get("email", "")),
            email=user_info.get("email"),
            display_name=user_info.get("name"),
            authentication_method=CredentialType.OAUTH_TOKEN,
            issuer=self.provider_name,
            subject=user_info.get("sub"),
            scopes=frozenset(credentials.get("scope", "").split()),
            metadata={
                "provider": self.provider_name,
                "user_info": user_info,
            },
        )

    async def validate_token(self, token: str) -> bool:
        """Validate an OAuth access token via token introspection.

        Args:
            token: Access token to validate

        Returns:
            True if the token is valid

        Raises:
            AuthenticationError: If token validation fails or introspection
                endpoint is not configured.
        """
        from yoda_foundation.exceptions import AuthenticationError

        if not token or not token.strip():
            return False

        introspection_url = getattr(self, "introspection_url", None)
        if not introspection_url:
            raise AuthenticationError(
                message="Token introspection endpoint not configured. "
                "Set introspection_url on the OAuthProvider or override validate_token().",
                auth_method="oauth",
                reason="introspection_not_configured",
            )

        try:
            import aiohttp

            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    introspection_url,
                    data={
                        "token": token,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response,
            ):
                if response.status != 200:
                    return False
                data = await response.json()
                return data.get("active", False) is True

        except ImportError:
            raise AuthenticationError(
                message="aiohttp is required for token introspection. "
                "Install it with: pip install aiohttp",
                auth_method="oauth",
                reason="missing_dependency",
            )
        except (AuthenticationError, OSError, ConnectionError) as e:
            raise AuthenticationError(
                message=f"Token introspection failed: {e}",
                auth_method="oauth",
                reason="introspection_error",
                cause=e,
            )

    async def refresh_token(self, refresh_token: str) -> TokenInfo | None:
        """
        Refresh an access token.

        Args:
            refresh_token: The refresh token

        Returns:
            New TokenInfo with refreshed access token

        Raises:
            AuthenticationError: If refresh fails

        Example:
            ```python
            if token.is_expired() and token.refresh_token:
                new_token = await provider.refresh_token(
                    token.refresh_token
                )
            ```

        Note:
            This is a placeholder. In production, make actual request
            to the token endpoint with refresh token grant.
        """
        from yoda_foundation.exceptions import AuthenticationError

        if not refresh_token:
            raise AuthenticationError(
                message="Refresh token is required",
                auth_method="oauth",
                reason="missing_refresh_token",
            )

        # NOTE: Placeholder implementation
        # In production, POST to token_url with refresh_token grant

        return TokenInfo(
            access_token=secrets.token_urlsafe(32),
            token_type="Bearer",
            expires_in=3600,
            refresh_token=refresh_token,
            scope=" ".join(self.scopes),
        )

    async def get_user_info(self, token: str) -> dict[str, Any] | None:
        """
        Get user information from the provider.

        Args:
            token: Valid access token

        Returns:
            User information dictionary

        Note:
            This is a placeholder. In production, make authenticated
            request to the userinfo endpoint.
        """
        if not self.userinfo_url:
            return None

        # NOTE: Placeholder implementation
        # In production, GET userinfo_url with Bearer token

        return {
            "sub": "user_123",
            "email": "user@example.com",
            "name": "Example User",
            "preferred_username": "user",
        }


class SAMLProvider(IdentityProvider):
    """
    SAML 2.0 identity provider.

    Supports SAML SSO flows for enterprise authentication.

    Attributes:
        entity_id: SAML entity ID
        sso_url: Single Sign-On URL
        x509_cert: X.509 certificate for signature verification
        name_id_format: SAML NameID format

    Example:
        ```python
        provider = SAMLProvider(
            provider_name="okta",
            entity_id="https://company.okta.com",
            sso_url="https://company.okta.com/app/sso/saml",
            x509_cert=cert_content,
        )

        # Generate SAML request
        saml_request = provider.generate_saml_request(
            acs_url="https://app.com/saml/acs",
        )

        # Process SAML response
        identity = await provider.authenticate({
            "saml_response": saml_response,
        })
        ```
    """

    def __init__(
        self,
        provider_name: str,
        entity_id: str,
        sso_url: str,
        x509_cert: str | None = None,
        name_id_format: str = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize SAML provider.

        Args:
            provider_name: Name of the provider
            entity_id: SAML entity ID
            sso_url: Single Sign-On URL
            x509_cert: X.509 certificate for verification
            name_id_format: SAML NameID format
            config: Additional configuration
        """
        super().__init__(provider_name, ProviderType.SAML, config)
        self.entity_id = entity_id
        self.sso_url = sso_url
        self.x509_cert = x509_cert
        self.name_id_format = name_id_format

    def generate_saml_request(self, acs_url: str) -> str:
        """
        Generate SAML authentication request.

        Args:
            acs_url: Assertion Consumer Service URL

        Returns:
            Base64-encoded SAML request

        Note:
            This is a placeholder. In production, use a SAML library
            like python3-saml to generate proper SAML requests.
        """
        # NOTE: Placeholder implementation
        # In production, use python3-saml or similar library
        import base64

        saml_request = f"""
        <samlp:AuthnRequest
            xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
            ID="_{secrets.token_urlsafe(16)}"
            Version="2.0"
            IssueInstant="{datetime.now(UTC).isoformat()}"
            AssertionConsumerServiceURL="{acs_url}">
        </samlp:AuthnRequest>
        """

        return base64.b64encode(saml_request.encode()).decode()

    async def authenticate(
        self,
        credentials: dict[str, Any],
    ) -> UserIdentity:
        """
        Authenticate user with SAML response.

        Args:
            credentials: Dictionary containing "saml_response"

        Returns:
            UserIdentity for the authenticated user

        Raises:
            AuthenticationError: If authentication fails

        Note:
            This is a placeholder. In production, properly validate
            SAML response signature and assertions.
        """
        from yoda_foundation.exceptions import AuthenticationError

        saml_response = credentials.get("saml_response")
        if not saml_response:
            raise AuthenticationError(
                message="SAML response is required",
                auth_method="saml",
                reason="missing_response",
            )

        # NOTE: Placeholder implementation
        # In production, validate SAML response using python3-saml

        # Extract user attributes from SAML response
        # This would normally come from parsing the response
        return UserIdentity(
            user_id="saml_user_123",
            username="saml_user",
            email="user@company.com",
            authentication_method=CredentialType.SAML,
            issuer=self.entity_id,
            metadata={
                "provider": self.provider_name,
                "name_id_format": self.name_id_format,
            },
        )

    async def validate_token(self, token: str) -> bool:
        """
        Validate a SAML assertion.

        Args:
            token: SAML assertion

        Returns:
            True if valid

        Note:
            SAML typically doesn't use tokens in the same way as OAuth.
            This is provided for interface compatibility.
        """
        # SAML uses assertions, not tokens
        return bool(token)


class APIKeyProvider(IdentityProvider):
    """
    API key-based identity provider.

    Simple authentication using API keys for programmatic access.

    Attributes:
        key_prefix: Required API key prefix (e.g., "sk_live_")
        key_store: Storage for API keys

    Example:
        ```python
        provider = APIKeyProvider(
            provider_name="internal",
            key_prefix="sk_live_",
        )

        # Register API key
        await provider.register_key(
            api_key="sk_live_abc123...",
            user_id="user_123",
            scopes=["api.read", "api.write"],
        )

        # Authenticate with API key
        identity = await provider.authenticate({
            "api_key": "sk_live_abc123...",
        })
        ```
    """

    def __init__(
        self,
        provider_name: str,
        key_prefix: str = "sk_",
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize API key provider.

        Args:
            provider_name: Name of the provider
            key_prefix: Required key prefix
            config: Additional configuration
        """
        super().__init__(provider_name, ProviderType.API_KEY, config)
        self.key_prefix = key_prefix
        # NOTE: In production, use a proper key-value store
        self._key_store: dict[str, dict[str, Any]] = {}

    async def register_key(
        self,
        api_key: str,
        user_id: str,
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Register a new API key.

        Args:
            api_key: The API key
            user_id: User who owns the key
            scopes: Scopes granted to the key
            metadata: Additional metadata

        Example:
            ```python
            api_key = f"sk_live_{secrets.token_urlsafe(32)}"
            await provider.register_key(
                api_key=api_key,
                user_id="user_123",
                scopes=["api.read", "api.write"],
            )
            ```
        """
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        self._key_store[key_hash] = {
            "user_id": user_id,
            "scopes": scopes or [],
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": metadata or {},
        }

    async def authenticate(
        self,
        credentials: dict[str, Any],
    ) -> UserIdentity:
        """
        Authenticate user with API key.

        Args:
            credentials: Dictionary containing "api_key"

        Returns:
            UserIdentity for the API key owner

        Raises:
            AuthenticationError: If authentication fails
        """
        from yoda_foundation.exceptions import AuthenticationError

        api_key = credentials.get("api_key")
        if not api_key:
            raise AuthenticationError(
                message="API key is required",
                auth_method="api_key",
                reason="missing_key",
            )

        # Validate format
        if not api_key.startswith(self.key_prefix):
            raise AuthenticationError(
                message=f"Invalid API key format (expected prefix: {self.key_prefix})",
                auth_method="api_key",
                reason="invalid_format",
            )

        # Look up key
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_data = self._key_store.get(key_hash)

        if not key_data:
            raise AuthenticationError(
                message="Invalid API key",
                auth_method="api_key",
                reason="invalid_key",
            )

        # Create identity
        return UserIdentity(
            user_id=key_data["user_id"],
            username=f"apikey_{key_hash[:8]}",
            authentication_method=CredentialType.API_KEY,
            scopes=frozenset(key_data.get("scopes", [])),
            metadata={
                "provider": self.provider_name,
                "key_prefix": api_key[:12],
                **key_data.get("metadata", {}),
            },
        )

    async def validate_token(self, token: str) -> bool:
        """
        Validate an API key.

        Args:
            token: API key to validate

        Returns:
            True if valid
        """
        if not token.startswith(self.key_prefix):
            return False

        key_hash = hashlib.sha256(token.encode()).hexdigest()
        return key_hash in self._key_store

    async def revoke_token(self, token: str) -> bool:
        """
        Revoke an API key.

        Args:
            token: API key to revoke

        Returns:
            True if revocation succeeded

        Example:
            ```python
            # Revoke compromised key
            await provider.revoke_token("sk_live_abc123...")
            ```
        """
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        if key_hash in self._key_store:
            del self._key_store[key_hash]
            return True
        return False
