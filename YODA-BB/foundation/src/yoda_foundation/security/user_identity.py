"""
User identity components for the Agentic AI Component Library.

This module provides user authentication context including credentials,
sessions, and identity management for human users.

Example:
    ```python
    from yoda_foundation.security import (
        UserIdentity,
        UserSession,
        UserCredentials,
    )

    # Create user identity from JWT
    identity = await UserIdentity.from_jwt_token(
        token="eyJ0eXAiOiJKV1QiLCJhbGc...",
        issuer="https://auth.company.com",
    )

    # Create session
    session = await UserSession.create(
        user_identity=identity,
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0...",
    )

    # Validate credentials
    creds = UserCredentials.from_password(
        username="alice@company.com",
        password="secure_password",
    )
    is_valid = await creds.validate()
    ```
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

from yoda_foundation.security.context import Permission


if TYPE_CHECKING:
    from yoda_foundation.security.context import SecurityContext


class CredentialType(Enum):
    """Type of user credential."""

    PASSWORD = "password"
    JWT = "jwt"
    OAUTH_TOKEN = "oauth_token"
    API_KEY = "api_key"
    SAML = "saml"
    CERTIFICATE = "certificate"


class SessionStatus(Enum):
    """Status of a user session."""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class UserIdentity:
    """
    Represents a user's identity and authentication context.

    Contains information about the authenticated user including their
    unique identifier, attributes, and authentication metadata.

    Attributes:
        user_id: Unique identifier for the user
        username: Human-readable username
        email: User's email address
        tenant_id: Tenant identifier for multi-tenancy
        display_name: User's display name
        attributes: Additional user attributes
        authentication_method: How the user authenticated
        authenticated_at: When the user authenticated
        expires_at: When the authentication expires
        issuer: Identity provider that issued the authentication
        subject: Subject identifier from the IdP
        scopes: OAuth scopes or permissions granted
        groups: Groups the user belongs to
        metadata: Additional metadata

    Example:
        ```python
        identity = UserIdentity(
            user_id="user_123",
            username="alice",
            email="alice@company.com",
            tenant_id="tenant_456",
            authentication_method=CredentialType.JWT,
            scopes=frozenset(["read:documents", "write:documents"]),
        )

        # Check if identity is valid
        if identity.is_valid():
            context = identity.to_security_context()
            await process_request(context)
        ```
    """

    user_id: str
    username: str
    email: str | None = None
    tenant_id: str | None = None
    display_name: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    authentication_method: CredentialType | None = None
    authenticated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    issuer: str | None = None
    subject: str | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)
    groups: frozenset[str] = field(default_factory=frozenset)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate and normalize the identity."""
        # Ensure scopes is a frozenset
        if isinstance(self.scopes, (list, set)):
            object.__setattr__(self, "scopes", frozenset(self.scopes))

        # Ensure groups is a frozenset
        if isinstance(self.groups, (list, set)):
            object.__setattr__(self, "groups", frozenset(self.groups))

    @property
    def is_expired(self) -> bool:
        """Check if the identity has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def is_valid(self) -> bool:
        """
        Check if the identity is currently valid.

        Returns:
            True if the identity is valid and not expired

        Example:
            ```python
            if not identity.is_valid():
                raise AuthenticationError(
                    message="User identity has expired",
                    reason="identity_expired",
                )
            ```
        """
        return not self.is_expired

    def has_scope(self, scope: str) -> bool:
        """
        Check if the identity has a specific OAuth scope.

        Args:
            scope: Scope to check

        Returns:
            True if the scope is granted

        Example:
            ```python
            if identity.has_scope("admin:users"):
                await list_all_users()
            ```
        """
        return scope in self.scopes

    def has_group(self, group: str) -> bool:
        """
        Check if the user belongs to a specific group.

        Args:
            group: Group name

        Returns:
            True if the user is in the group

        Example:
            ```python
            if identity.has_group("administrators"):
                show_admin_features()
            ```
        """
        return group in self.groups

    def to_security_context(
        self,
        permissions: frozenset[Permission] | None = None,
        roles: frozenset[str] | None = None,
        session_id: str | None = None,
        correlation_id: str | None = None,
    ) -> SecurityContext:
        """
        Convert user identity to a security context.

        Args:
            permissions: Permissions to grant
            roles: Roles to assign
            session_id: Session identifier
            correlation_id: Correlation ID for tracing

        Returns:
            SecurityContext for the user

        Example:
            ```python
            # Convert identity to context
            context = identity.to_security_context(
                permissions=frozenset([
                    Permission("document", "read"),
                    Permission("document", "write"),
                ]),
                roles=frozenset(["editor"]),
            )
            ```
        """
        from yoda_foundation.security.context import ContextType, SecurityContext

        return SecurityContext(
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            context_type=ContextType.USER,
            permissions=permissions or frozenset(),
            roles=roles or frozenset(),
            session_id=session_id,
            correlation_id=correlation_id,
            metadata={
                "username": self.username,
                "email": self.email,
                "display_name": self.display_name,
                "authentication_method": self.authentication_method.value
                if self.authentication_method
                else None,
                "issuer": self.issuer,
                "scopes": list(self.scopes),
                "groups": list(self.groups),
                **self.metadata,
            },
            created_at=self.authenticated_at,
            expires_at=self.expires_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert identity to dictionary for serialization.

        Returns:
            Dictionary representation

        Example:
            ```python
            identity_dict = identity.to_dict()
            await cache.set(f"identity:{user_id}", identity_dict)
            ```
        """
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "attributes": self.attributes,
            "authentication_method": self.authentication_method.value
            if self.authentication_method
            else None,
            "authenticated_at": self.authenticated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "issuer": self.issuer,
            "subject": self.subject,
            "scopes": list(self.scopes),
            "groups": list(self.groups),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserIdentity:
        """
        Create identity from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            UserIdentity instance

        Example:
            ```python
            identity_dict = await cache.get(f"identity:{user_id}")
            identity = UserIdentity.from_dict(identity_dict)
            ```
        """
        authenticated_at = data.get("authenticated_at")
        if isinstance(authenticated_at, str):
            authenticated_at = datetime.fromisoformat(authenticated_at)

        expires_at = data.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)

        auth_method = data.get("authentication_method")
        if auth_method and isinstance(auth_method, str):
            auth_method = CredentialType(auth_method)

        return cls(
            user_id=data["user_id"],
            username=data["username"],
            email=data.get("email"),
            tenant_id=data.get("tenant_id"),
            display_name=data.get("display_name"),
            attributes=data.get("attributes", {}),
            authentication_method=auth_method,
            authenticated_at=authenticated_at or datetime.now(UTC),
            expires_at=expires_at,
            issuer=data.get("issuer"),
            subject=data.get("subject"),
            scopes=frozenset(data.get("scopes", [])),
            groups=frozenset(data.get("groups", [])),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    async def from_jwt_token(
        cls,
        token: str,
        issuer: str,
        verify: bool = True,
    ) -> UserIdentity:
        """
        Create identity from a JWT token.

        Args:
            token: JWT token string
            issuer: Expected token issuer
            verify: Whether to verify the token signature

        Returns:
            UserIdentity parsed from the token

        Raises:
            AuthenticationError: If token is invalid or expired

        Example:
            ```python
            try:
                identity = await UserIdentity.from_jwt_token(
                    token=request.headers["Authorization"].split()[1],
                    issuer="https://auth.company.com",
                )
            except AuthenticationError as e:
                return 401, {"error": e.user_message}
            ```

        Note:
            This is a placeholder implementation. In production, use a
            proper JWT library like PyJWT with signature verification.
        """
        from yoda_foundation.exceptions import AuthenticationError

        # NOTE: This is a simplified implementation
        # In production, use PyJWT or similar library
        try:
            import base64
            import json

            # Decode JWT (without verification for now)
            parts = token.split(".")
            if len(parts) != 3:
                raise AuthenticationError(
                    message="Invalid JWT token format",
                    auth_method="jwt",
                    reason="invalid_format",
                )

            # Decode payload
            payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
            payload = json.loads(payload_bytes)

            # Validate issuer
            if verify and payload.get("iss") != issuer:
                raise AuthenticationError(
                    message="Token issuer mismatch",
                    auth_method="jwt",
                    reason="invalid_issuer",
                )

            # Validate expiration
            exp = payload.get("exp")
            if exp:
                exp_time = datetime.fromtimestamp(exp, tz=UTC)
                if datetime.now(UTC) > exp_time:
                    raise AuthenticationError(
                        message="JWT token has expired",
                        auth_method="jwt",
                        reason="token_expired",
                    )

            # Extract identity information
            return cls(
                user_id=payload.get("sub", ""),
                username=payload.get("preferred_username", payload.get("sub", "")),
                email=payload.get("email"),
                tenant_id=payload.get("tenant_id"),
                display_name=payload.get("name"),
                authentication_method=CredentialType.JWT,
                authenticated_at=datetime.fromtimestamp(
                    payload.get("iat", datetime.now(UTC).timestamp()),
                    tz=UTC,
                ),
                expires_at=datetime.fromtimestamp(exp, tz=UTC) if exp else None,
                issuer=payload.get("iss"),
                subject=payload.get("sub"),
                scopes=frozenset(payload.get("scope", "").split()),
                groups=frozenset(payload.get("groups", [])),
                metadata={"claims": payload},
            )

        except (ValueError, KeyError, json.JSONDecodeError) as e:
            raise AuthenticationError(
                message="Failed to parse JWT token",
                auth_method="jwt",
                reason="parse_error",
                cause=e,
            )


@dataclass
class UserSession:
    """
    Represents an active user session.

    Manages session lifecycle including creation, validation, and revocation.

    Attributes:
        session_id: Unique session identifier
        user_identity: The user's identity
        created_at: When the session was created
        expires_at: When the session expires
        last_activity_at: Last activity timestamp
        ip_address: Client IP address
        user_agent: Client user agent string
        device_id: Device identifier
        status: Current session status
        metadata: Additional session metadata

    Example:
        ```python
        # Create a new session
        session = await UserSession.create(
            user_identity=identity,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            ttl_seconds=3600,
        )

        # Validate session
        if session.is_valid():
            await session.update_activity()
        else:
            raise AuthenticationError(
                message="Session has expired",
                reason="session_expired",
            )
        ```
    """

    session_id: str
    user_identity: UserIdentity
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ip_address: str | None = None
    user_agent: str | None = None
    device_id: str | None = None
    status: SessionStatus = SessionStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def create(
        cls,
        user_identity: UserIdentity,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_id: str | None = None,
        ttl_seconds: int = 3600,
        metadata: dict[str, Any] | None = None,
    ) -> UserSession:
        """
        Create a new user session.

        Args:
            user_identity: The user's identity
            ip_address: Client IP address
            user_agent: Client user agent
            device_id: Device identifier
            ttl_seconds: Time-to-live in seconds
            metadata: Additional metadata

        Returns:
            New UserSession instance

        Example:
            ```python
            session = await UserSession.create(
                user_identity=identity,
                ip_address="192.168.1.1",
                ttl_seconds=7200,  # 2 hours
            )
            ```
        """
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        return cls(
            session_id=str(uuid.uuid4()),
            user_identity=user_identity,
            created_at=now,
            expires_at=expires_at,
            last_activity_at=now,
            ip_address=ip_address,
            user_agent=user_agent,
            device_id=device_id,
            status=SessionStatus.ACTIVE,
            metadata=metadata or {},
        )

    @property
    def is_expired(self) -> bool:
        """Check if the session has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def is_valid(self) -> bool:
        """
        Check if the session is currently valid.

        Returns:
            True if session is active and not expired

        Example:
            ```python
            if not session.is_valid():
                await session.revoke()
                raise AuthenticationError(
                    message="Session is no longer valid",
                    reason="session_invalid",
                )
            ```
        """
        return (
            self.status == SessionStatus.ACTIVE
            and not self.is_expired
            and self.user_identity.is_valid()
        )

    async def update_activity(self) -> None:
        """
        Update the last activity timestamp.

        Example:
            ```python
            # Update on each request
            await session.update_activity()
            ```
        """
        object.__setattr__(self, "last_activity_at", datetime.now(UTC))

    async def revoke(self) -> None:
        """
        Revoke the session.

        Example:
            ```python
            # On logout
            await session.revoke()
            ```
        """
        object.__setattr__(self, "status", SessionStatus.REVOKED)

    async def suspend(self) -> None:
        """
        Suspend the session temporarily.

        Example:
            ```python
            # On suspicious activity
            await session.suspend()
            ```
        """
        object.__setattr__(self, "status", SessionStatus.SUSPENDED)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert session to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "session_id": self.session_id,
            "user_identity": self.user_identity.to_dict(),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_activity_at": self.last_activity_at.isoformat(),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "device_id": self.device_id,
            "status": self.status.value,
            "metadata": self.metadata,
        }


class UserCredentials(ABC):
    """
    Abstract base class for user credentials.

    Provides interface for different credential types including
    passwords, API keys, OAuth tokens, etc.

    Example:
        ```python
        class CustomCredentials(UserCredentials):
            async def validate(self) -> bool:
                # Custom validation logic
                return await verify_custom_auth()

            async def to_identity(self) -> UserIdentity:
                # Convert to identity
                return UserIdentity(...)
        ```
    """

    @abstractmethod
    async def validate(self) -> bool:
        """
        Validate the credentials.

        Returns:
            True if credentials are valid

        Raises:
            AuthenticationError: If validation fails
        """
        pass

    @abstractmethod
    async def to_identity(self) -> UserIdentity:
        """
        Convert validated credentials to user identity.

        Returns:
            UserIdentity for the authenticated user

        Raises:
            AuthenticationError: If credentials are invalid
        """
        pass


@dataclass
class PasswordCredentials(UserCredentials):
    """
    Password-based user credentials.

    Attributes:
        username: Username or email
        password: Plain-text password (hashed for storage)
        tenant_id: Optional tenant identifier

    Example:
        ```python
        creds = PasswordCredentials(
            username="alice@company.com",
            password="secure_password",
        )

        if await creds.validate():
            identity = await creds.to_identity()
        ```

    Warning:
        This is a simplified implementation. In production, use
        proper password hashing (bcrypt, argon2) and verification.
    """

    username: str
    password: str
    tenant_id: str | None = None

    def _hash_password(self, password: str) -> str:
        """Hash a password for storage."""
        # NOTE: This is NOT secure - use bcrypt/argon2 in production
        return hashlib.sha256(password.encode()).hexdigest()

    async def validate(self) -> bool:
        """
        Validate the password credentials.

        Returns:
            True if credentials are valid

        Raises:
            AuthenticationError: If validation fails

        Note:
            This is a placeholder. In production, verify against
            a secure credential store with proper password hashing.
        """
        from yoda_foundation.exceptions import AuthenticationError

        # NOTE: Placeholder implementation
        # In production, verify against a credential store
        if not self.username or not self.password:
            raise AuthenticationError(
                message="Username and password are required",
                auth_method="password",
                reason="missing_credentials",
            )

        # Placeholder validation
        return True

    async def to_identity(self) -> UserIdentity:
        """
        Convert validated credentials to user identity.

        Returns:
            UserIdentity for the authenticated user

        Raises:
            AuthenticationError: If credentials are invalid
        """
        if not await self.validate():
            from yoda_foundation.exceptions import AuthenticationError

            raise AuthenticationError(
                message="Invalid credentials",
                auth_method="password",
                reason="invalid_credentials",
            )

        # NOTE: In production, fetch user details from user store
        return UserIdentity(
            user_id=f"user:{self.username}",
            username=self.username,
            email=self.username if "@" in self.username else None,
            tenant_id=self.tenant_id,
            authentication_method=CredentialType.PASSWORD,
        )


@dataclass
class APIKeyCredentials(UserCredentials):
    """
    API key-based credentials.

    Attributes:
        api_key: The API key
        tenant_id: Optional tenant identifier

    Example:
        ```python
        creds = APIKeyCredentials(
            api_key="sk_live_abc123...",
        )

        if await creds.validate():
            identity = await creds.to_identity()
        ```
    """

    api_key: str
    tenant_id: str | None = None

    async def validate(self) -> bool:
        """
        Validate the API key.

        Returns:
            True if API key is valid

        Raises:
            AuthenticationError: If validation fails

        Note:
            This is a placeholder. In production, verify against
            an API key store with proper rotation and scoping.
        """
        from yoda_foundation.exceptions import AuthenticationError

        if not self.api_key:
            raise AuthenticationError(
                message="API key is required",
                auth_method="api_key",
                reason="missing_api_key",
            )

        # Validate format (e.g., sk_live_ or sk_test_ prefix)
        if not self.api_key.startswith(("sk_live_", "sk_test_")):
            raise AuthenticationError(
                message="Invalid API key format",
                auth_method="api_key",
                reason="invalid_format",
            )

        # NOTE: In production, verify against key store
        return True

    async def to_identity(self) -> UserIdentity:
        """
        Convert validated API key to user identity.

        Returns:
            UserIdentity for the API key owner

        Raises:
            AuthenticationError: If API key is invalid
        """
        if not await self.validate():
            from yoda_foundation.exceptions import AuthenticationError

            raise AuthenticationError(
                message="Invalid API key",
                auth_method="api_key",
                reason="invalid_api_key",
            )

        # Generate stable user ID from API key
        key_hash = hashlib.sha256(self.api_key.encode()).hexdigest()[:16]

        return UserIdentity(
            user_id=f"apikey:{key_hash}",
            username=f"apikey_{key_hash}",
            tenant_id=self.tenant_id,
            authentication_method=CredentialType.API_KEY,
            metadata={"key_prefix": self.api_key[:12]},
        )


@dataclass
class OAuthTokenCredentials(UserCredentials):
    """
    OAuth 2.0 token-based credentials.

    Attributes:
        access_token: OAuth access token
        token_type: Token type (usually "Bearer")
        scope: OAuth scopes
        refresh_token: Optional refresh token
        expires_in: Token expiry in seconds

    Example:
        ```python
        creds = OAuthTokenCredentials(
            access_token="eyJhbGciOi.EXAMPLE_TOKEN",
            token_type="Bearer",
            scope="openid email profile",
        )

        identity = await creds.to_identity()
        ```
    """

    access_token: str
    token_type: str = "Bearer"
    scope: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None

    async def validate(self) -> bool:
        """
        Validate the OAuth token.

        Returns:
            True if token is valid

        Raises:
            AuthenticationError: If validation fails

        Note:
            This is a placeholder. In production, validate against
            the OAuth provider's token introspection endpoint.
        """
        from yoda_foundation.exceptions import AuthenticationError

        if not self.access_token:
            raise AuthenticationError(
                message="Access token is required",
                auth_method="oauth_token",
                reason="missing_token",
            )

        # NOTE: In production, validate via token introspection
        return True

    async def to_identity(self) -> UserIdentity:
        """
        Convert validated OAuth token to user identity.

        Returns:
            UserIdentity for the OAuth user

        Raises:
            AuthenticationError: If token is invalid
        """
        if not await self.validate():
            from yoda_foundation.exceptions import AuthenticationError

            raise AuthenticationError(
                message="Invalid OAuth token",
                auth_method="oauth_token",
                reason="invalid_token",
            )

        # NOTE: In production, fetch user info from OAuth provider
        # (e.g., /userinfo endpoint)
        expires_at = None
        if self.expires_in:
            expires_at = datetime.now(UTC) + timedelta(seconds=self.expires_in)

        return UserIdentity(
            user_id=f"oauth:{hashlib.sha256(self.access_token.encode()).hexdigest()[:16]}",
            username="oauth_user",
            authentication_method=CredentialType.OAUTH_TOKEN,
            scopes=frozenset(self.scope.split()) if self.scope else frozenset(),
            expires_at=expires_at,
            metadata={
                "token_type": self.token_type,
                "has_refresh_token": self.refresh_token is not None,
            },
        )
