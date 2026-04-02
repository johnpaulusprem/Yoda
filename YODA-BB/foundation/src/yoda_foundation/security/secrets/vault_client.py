"""
HashiCorp Vault client for the Agentic AI Component Library.

This module provides a secure, async client for interacting with HashiCorp Vault
for secrets management. It handles authentication, secret operations, and
integrates with the library's security context and audit logging.

Example:
    ```python
    from yoda_foundation.security.secrets import (
        VaultClient,
        VaultConfig,
    )
    from yoda_foundation.security import create_security_context

    # Configure Vault client
    config = VaultConfig(
        url="https://vault.example.com:8200",
        token="hvs.your-token-here",
        namespace="my-namespace",
    )

    # Create client
    client = VaultClient(config)

    # Create security context
    context = create_security_context(
        user_id="user_123",
        permissions=["secrets.read", "secrets.write"],
    )

    # Get a secret
    secret = await client.get_secret(
        path="secret/data/myapp/config",
        security_context=context,
    )

    # Set a secret
    await client.set_secret(
        path="secret/data/myapp/config",
        data={"api_key": "secret-value"},
        security_context=context,
    )

    # List secrets
    secrets = await client.list_secrets(
        path="secret/metadata/myapp",
        security_context=context,
    )

    # Rotate a secret
    new_secret = await client.rotate_secret(
        path="secret/data/myapp/config",
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Protocol
from urllib.parse import urljoin

from yoda_foundation.security.context import SecurityContext
from yoda_foundation.security.data_governance.audit_logger import (
    AuditLogger,
    AuditAction,
    AuditStatus,
)
from yoda_foundation.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ResourceNotFoundError,
    ResourceUnavailableError,
    ValidationError,
)
from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)
from yoda_foundation.observability.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Secrets-Specific Exceptions
# =============================================================================


class SecretsError(AgenticBaseException):
    """
    Base exception for secrets management errors.

    Provides common attributes for secrets-related operations.

    Attributes:
        secret_path: Path to the secret in Vault
        operation: The operation that failed

    Example:
        ```python
        raise SecretsError(
            message="Secret operation failed",
            secret_path="secret/data/myapp/config",
            operation="read",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Secrets operation failed",
        *,
        secret_path: Optional[str] = None,
        operation: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
        severity: ErrorSeverity = ErrorSeverity.HIGH,
        retryable: bool = False,
    ) -> None:
        """
        Initialize secrets error.

        Args:
            message: Human-readable error description
            secret_path: Path to the secret
            operation: The operation that failed
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
            severity: Error severity level
            retryable: Whether the operation can be retried
        """
        self.secret_path = secret_path
        self.operation = operation

        extra_details = {
            "secret_path": secret_path,
            "operation": operation,
        }

        merged_details = {**extra_details, **(details or {})}

        super().__init__(
            message=message,
            category=ErrorCategory.RESOURCE,
            severity=severity,
            retryable=retryable,
            user_message="A secrets operation failed. Please try again.",
            suggestions=suggestions or [
                "Check Vault connectivity",
                "Verify your access permissions",
                "Ensure the secret path is correct",
            ],
            cause=cause,
            details=merged_details,
        )


class VaultConnectionError(SecretsError):
    """
    Vault connection error.

    Raised when unable to connect to the Vault server.

    Example:
        ```python
        raise VaultConnectionError(
            vault_url="https://vault.example.com:8200",
            cause=original_error,
        )
        ```
    """

    def __init__(
        self,
        message: str = "Failed to connect to Vault server",
        *,
        vault_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        suggestions: Optional[List[str]] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize Vault connection error.

        Args:
            message: Human-readable error description
            vault_url: The Vault URL that failed
            timeout_seconds: The timeout that was exceeded
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.vault_url = vault_url
        self.timeout_seconds = timeout_seconds

        extra_details = {
            "vault_url": vault_url,
            "timeout_seconds": timeout_seconds,
        }

        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "Check Vault server status",
            "Verify network connectivity",
            "Check firewall rules",
        ]
        if timeout_seconds:
            default_suggestions.append(f"Consider increasing timeout from {timeout_seconds}s")

        super().__init__(
            message=message,
            operation="connect",
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=merged_details,
            severity=ErrorSeverity.HIGH,
            retryable=True,
        )
        self.user_message = "Unable to connect to the secrets vault. Please try again later."


class SecretNotFoundError(SecretsError):
    """
    Secret not found error.

    Raised when a requested secret does not exist in Vault.

    Example:
        ```python
        raise SecretNotFoundError(
            secret_path="secret/data/myapp/missing",
        )
        ```
    """

    def __init__(
        self,
        message: str = "",
        *,
        secret_path: str,
        suggestions: Optional[List[str]] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize secret not found error.

        Args:
            message: Human-readable error description
            secret_path: Path to the missing secret
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        if not message:
            message = f"Secret not found at path: '{secret_path}'"

        default_suggestions = [
            "Verify the secret path is correct",
            "Check if the secret has been deleted",
            "Ensure you have read permissions for this path",
        ]

        super().__init__(
            message=message,
            secret_path=secret_path,
            operation="read",
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=details,
            severity=ErrorSeverity.LOW,
            retryable=False,
        )
        self.user_message = "The requested secret was not found."


class SecretAccessDeniedError(SecretsError):
    """
    Secret access denied error.

    Raised when access to a secret is denied due to insufficient permissions.

    Example:
        ```python
        raise SecretAccessDeniedError(
            secret_path="secret/data/admin/config",
            required_permission="secrets.read",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Access denied to secret",
        *,
        secret_path: str,
        required_permission: Optional[str] = None,
        operation: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize secret access denied error.

        Args:
            message: Human-readable error description
            secret_path: Path to the secret
            required_permission: The permission that was required
            operation: The operation that was denied
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.required_permission = required_permission

        extra_details = {
            "required_permission": required_permission,
        }

        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "Contact your administrator to request access",
            "Verify you are using the correct credentials",
        ]
        if required_permission:
            default_suggestions.insert(
                0, f"Request the '{required_permission}' permission"
            )

        super().__init__(
            message=message,
            secret_path=secret_path,
            operation=operation,
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=merged_details,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
        )
        self.user_message = "You don't have permission to access this secret."


# =============================================================================
# Configuration and Data Classes
# =============================================================================


class AuthMethod(Enum):
    """
    Vault authentication methods.

    Supported authentication methods for connecting to Vault.
    """

    TOKEN = "token"
    APPROLE = "approle"
    KUBERNETES = "kubernetes"
    AWS_IAM = "aws_iam"
    LDAP = "ldap"


@dataclass
class VaultConfig:
    """
    Configuration for HashiCorp Vault client.

    Holds all configuration needed to connect to and authenticate
    with a Vault server.

    Attributes:
        url: Vault server URL (e.g., "https://vault.example.com:8200")
        token: Vault token for authentication (if using token auth)
        namespace: Vault namespace (Enterprise feature)
        timeout: Request timeout in seconds
        verify_ssl: Whether to verify SSL certificates
        ca_cert: Path to custom CA certificate
        auth_method: Authentication method to use
        role_id: AppRole role ID (for approle auth)
        secret_id: AppRole secret ID (for approle auth)
        mount_point: Default secrets engine mount point

    Example:
        ```python
        config = VaultConfig(
            url="https://vault.example.com:8200",
            token="hvs.your-token",
            namespace="my-team",
            timeout=30.0,
            verify_ssl=True,
        )
        ```
    """

    url: str
    token: Optional[str] = None
    namespace: Optional[str] = None
    timeout: float = 30.0
    verify_ssl: bool = True
    ca_cert: Optional[str] = None
    auth_method: AuthMethod = AuthMethod.TOKEN
    role_id: Optional[str] = None
    secret_id: Optional[str] = None
    mount_point: str = "secret"

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not self.url:
            raise ValidationError(
                message="Vault URL is required",
                suggestions=["Provide a valid Vault URL"],
            )

        # Ensure URL doesn't have trailing slash
        self.url = self.url.rstrip("/")

        # Validate auth method requirements
        if self.auth_method == AuthMethod.TOKEN and not self.token:
            raise ValidationError(
                message="Token is required for token authentication",
                suggestions=["Provide a Vault token or use a different auth method"],
            )

        if self.auth_method == AuthMethod.APPROLE:
            if not self.role_id or not self.secret_id:
                raise ValidationError(
                    message="role_id and secret_id are required for AppRole authentication",
                    suggestions=["Provide both role_id and secret_id"],
                )


@dataclass
class SecretMetadata:
    """
    Metadata for a secret in Vault.

    Contains information about the secret's versioning and lifecycle.

    Attributes:
        created_time: When the secret version was created
        deletion_time: When the secret will be deleted (if scheduled)
        destroyed: Whether this version has been destroyed
        version: Version number of the secret
        custom_metadata: User-defined metadata

    Example:
        ```python
        metadata = SecretMetadata(
            created_time=datetime.now(timezone.utc),
            version=3,
            custom_metadata={"environment": "production"},
        )
        ```
    """

    created_time: Optional[datetime] = None
    deletion_time: Optional[datetime] = None
    destroyed: bool = False
    version: int = 0
    custom_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "created_time": self.created_time.isoformat() if self.created_time else None,
            "deletion_time": self.deletion_time.isoformat() if self.deletion_time else None,
            "destroyed": self.destroyed,
            "version": self.version,
            "custom_metadata": self.custom_metadata,
        }


@dataclass
class SecretResult:
    """
    Result of a secret operation.

    Contains the secret data and associated metadata.

    Attributes:
        data: The secret data (key-value pairs)
        metadata: Secret metadata
        path: Path where the secret is stored

    Example:
        ```python
        result = SecretResult(
            data={"api_key": "secret-value", "api_secret": "another-secret"},
            metadata=SecretMetadata(version=2),
            path="secret/data/myapp/config",
        )
        ```
    """

    data: Dict[str, Any]
    metadata: SecretMetadata
    path: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "data": self.data,
            "metadata": self.metadata.to_dict(),
            "path": self.path,
        }


# =============================================================================
# Vault HTTP Client Protocol
# =============================================================================


class VaultHTTPClient(Protocol):
    """
    Protocol for Vault HTTP client implementations.

    Allows for different HTTP client implementations (aiohttp, httpx, etc.)
    or mock implementations for testing.
    """

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to Vault.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, LIST)
            path: API path
            headers: Request headers
            json: JSON body
            timeout: Request timeout

        Returns:
            Response data as dictionary
        """
        ...

    async def close(self) -> None:
        """Close the HTTP client."""
        ...


# =============================================================================
# Vault Client Implementation
# =============================================================================


class VaultClient:
    """
    Async HashiCorp Vault client for secrets management.

    Provides secure, audited access to secrets stored in HashiCorp Vault.
    Integrates with the library's security context and audit logging.

    Attributes:
        config: Vault configuration
        audit_logger: Optional audit logger for tracking secret operations

    Example:
        ```python
        from yoda_foundation.security.secrets import VaultClient, VaultConfig
        from yoda_foundation.security import create_security_context

        # Create configuration
        config = VaultConfig(
            url="https://vault.example.com:8200",
            token="hvs.your-token",
        )

        # Create client
        client = VaultClient(config)

        # Create security context with appropriate permissions
        context = create_security_context(
            user_id="user_123",
            permissions=["secrets.read", "secrets.write", "secrets.list"],
        )

        # Read a secret
        secret = await client.get_secret(
            path="secret/data/myapp/database",
            security_context=context,
        )
        print(f"Database password: {secret['password']}")

        # Write a secret
        await client.set_secret(
            path="secret/data/myapp/api",
            data={"key": "new-api-key", "secret": "api-secret"},
            security_context=context,
        )

        # List secrets in a path
        secrets = await client.list_secrets(
            path="secret/metadata/myapp",
            security_context=context,
        )
        print(f"Secrets: {secrets}")

        # Rotate a secret (generates new version)
        new_secret = await client.rotate_secret(
            path="secret/data/myapp/api",
            security_context=context,
        )

        # Clean up
        await client.close()
        ```

    Note:
        All public methods require a SecurityContext with appropriate
        permissions. Operations are audited when an audit logger is configured.
    """

    # Permission constants
    PERMISSION_READ = "secrets.read"
    PERMISSION_WRITE = "secrets.write"
    PERMISSION_DELETE = "secrets.delete"
    PERMISSION_LIST = "secrets.list"

    def __init__(
        self,
        config: VaultConfig,
        audit_logger: Optional[AuditLogger] = None,
        http_client: Optional[VaultHTTPClient] = None,
    ) -> None:
        """
        Initialize Vault client.

        Args:
            config: Vault configuration
            audit_logger: Optional audit logger for tracking operations
            http_client: Optional custom HTTP client (for testing)

        Example:
            ```python
            config = VaultConfig(
                url="https://vault.example.com:8200",
                token="hvs.your-token",
            )

            # With audit logging
            audit = AuditLogger()
            client = VaultClient(config, audit_logger=audit)

            # Without audit logging
            client = VaultClient(config)
            ```
        """
        self._config = config
        self._audit_logger = audit_logger
        self._http_client = http_client
        self._session: Optional[Any] = None
        self._lock = asyncio.Lock()

    @property
    def config(self) -> VaultConfig:
        """Get the Vault configuration."""
        return self._config

    async def _ensure_session(self) -> Any:
        """
        Ensure an HTTP session is available.

        Creates a new aiohttp session if one doesn't exist.

        Returns:
            aiohttp ClientSession

        Raises:
            VaultConnectionError: If unable to create session
        """
        if self._session is None:
            async with self._lock:
                if self._session is None:
                    try:
                        import aiohttp

                        # Configure SSL context
                        ssl_context: Optional[ssl.SSLContext] = None
                        if self._config.verify_ssl:
                            ssl_context = ssl.create_default_context()
                            if self._config.ca_cert:
                                ssl_context.load_verify_locations(self._config.ca_cert)
                        else:
                            ssl_context = ssl.create_default_context()
                            ssl_context.check_hostname = False
                            ssl_context.verify_mode = ssl.CERT_NONE

                        timeout = aiohttp.ClientTimeout(total=self._config.timeout)
                        connector = aiohttp.TCPConnector(ssl=ssl_context)

                        self._session = aiohttp.ClientSession(
                            timeout=timeout,
                            connector=connector,
                        )
                    except ImportError as e:
                        raise VaultConnectionError(
                            message="aiohttp is required for Vault client",
                            vault_url=self._config.url,
                            cause=e,
                            suggestions=["Install aiohttp: pip install aiohttp"],
                        )
                    except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
                        raise VaultConnectionError(
                            message=f"Failed to create HTTP session: {e}",
                            vault_url=self._config.url,
                            cause=e,
                        )

        return self._session

    def _build_headers(self) -> Dict[str, str]:
        """
        Build request headers for Vault API calls.

        Returns:
            Dictionary of headers
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if self._config.token:
            headers["X-Vault-Token"] = self._config.token

        if self._config.namespace:
            headers["X-Vault-Namespace"] = self._config.namespace

        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to Vault.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, LIST)
            path: API path (relative to Vault URL)
            json_data: Optional JSON body

        Returns:
            Response data as dictionary

        Raises:
            VaultConnectionError: If connection fails
            SecretNotFoundError: If resource not found
            SecretAccessDeniedError: If access denied
            SecretsError: For other Vault errors
        """
        # Use custom HTTP client if provided (for testing)
        if self._http_client:
            return await self._http_client.request(
                method,
                path,
                headers=self._build_headers(),
                json=json_data,
                timeout=self._config.timeout,
            )

        session = await self._ensure_session()
        url = urljoin(self._config.url + "/", path.lstrip("/"))
        headers = self._build_headers()

        # Handle LIST method (Vault-specific)
        actual_method = method
        if method.upper() == "LIST":
            actual_method = "GET"
            if "?" in url:
                url += "&list=true"
            else:
                url += "?list=true"

        try:
            async with session.request(
                actual_method,
                url,
                headers=headers,
                json=json_data,
            ) as response:
                # Handle different response codes
                if response.status == 200:
                    return await response.json()

                if response.status == 204:
                    return {}

                if response.status == 404:
                    raise SecretNotFoundError(
                        secret_path=path,
                    )

                if response.status == 403:
                    raise SecretAccessDeniedError(
                        message="Vault access denied",
                        secret_path=path,
                        operation=method.lower(),
                    )

                if response.status == 401:
                    raise AuthenticationError(
                        message="Vault authentication failed",
                        auth_method=self._config.auth_method.value,
                        reason="invalid_token",
                    )

                # Handle other errors
                try:
                    error_data = await response.json()
                    errors = error_data.get("errors", [])
                    error_msg = "; ".join(errors) if errors else f"HTTP {response.status}"
                except (ValueError, TypeError, KeyError):
                    error_msg = f"HTTP {response.status}: {await response.text()}"

                raise SecretsError(
                    message=f"Vault request failed: {error_msg}",
                    secret_path=path,
                    operation=method.lower(),
                    retryable=response.status >= 500,
                )

        except SecretNotFoundError:
            raise
        except SecretAccessDeniedError:
            raise
        except AuthenticationError:
            raise
        except SecretsError:
            raise
        except asyncio.TimeoutError as e:
            raise VaultConnectionError(
                message="Vault request timed out",
                vault_url=self._config.url,
                timeout_seconds=self._config.timeout,
                cause=e,
            )
        except (ConnectionError, OSError, ssl.SSLError) as e:
            raise VaultConnectionError(
                message=f"Vault request failed: {e}",
                vault_url=self._config.url,
                cause=e,
            )

    def _check_permission(
        self,
        security_context: SecurityContext,
        permission: str,
        path: str,
    ) -> None:
        """
        Check if security context has required permission.

        Args:
            security_context: Security context to check
            permission: Required permission
            path: Secret path being accessed

        Raises:
            AuthorizationError: If permission not granted
        """
        if not security_context.has_permission(permission):
            raise AuthorizationError(
                message=f"Permission denied: {permission}",
                required_permission=permission,
                resource=f"secret:{path}",
                user_id=security_context.user_id,
            )

    async def _audit_operation(
        self,
        action: AuditAction,
        path: str,
        status: AuditStatus,
        security_context: SecurityContext,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Audit a secret operation.

        Args:
            action: The audit action
            path: Secret path
            status: Operation status
            security_context: Security context
            metadata: Additional metadata
        """
        if self._audit_logger:
            try:
                await self._audit_logger.log(
                    action=action,
                    resource_type="secret",
                    resource_id=path,
                    status=status,
                    security_context=security_context,
                    metadata=metadata or {},
                )
            except (AgenticBaseException, ConnectionError, TimeoutError, OSError) as e:
                # Log error but don't fail the operation
                logger.warning(
                    "Failed to write secret audit entry",
                    exc_info=e,
                    path=path,
                    action=action.value,
                )

    def _normalize_path(self, path: str) -> str:
        """
        Normalize a secret path.

        Ensures consistent path format for Vault API calls.

        Args:
            path: The secret path to normalize

        Returns:
            Normalized path
        """
        # Remove leading/trailing slashes
        path = path.strip("/")

        # Handle KV v2 paths (add /data/ for data operations if not present)
        if not path.startswith(f"{self._config.mount_point}/data/") and \
           not path.startswith(f"{self._config.mount_point}/metadata/"):
            # Assume it's a shorthand path
            if path.startswith(self._config.mount_point + "/"):
                path = path.replace(
                    f"{self._config.mount_point}/",
                    f"{self._config.mount_point}/data/",
                    1,
                )
            else:
                path = f"{self._config.mount_point}/data/{path}"

        return f"/v1/{path}"

    def _normalize_metadata_path(self, path: str) -> str:
        """
        Normalize a secret path for metadata operations.

        Args:
            path: The secret path to normalize

        Returns:
            Normalized metadata path
        """
        path = path.strip("/")

        if not path.startswith(f"{self._config.mount_point}/metadata/"):
            if path.startswith(f"{self._config.mount_point}/data/"):
                path = path.replace("/data/", "/metadata/", 1)
            elif path.startswith(f"{self._config.mount_point}/"):
                path = path.replace(
                    f"{self._config.mount_point}/",
                    f"{self._config.mount_point}/metadata/",
                    1,
                )
            else:
                path = f"{self._config.mount_point}/metadata/{path}"

        return f"/v1/{path}"

    async def get_secret(
        self,
        path: str,
        security_context: SecurityContext,
        *,
        version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get a secret from Vault.

        Retrieves the secret data at the specified path. For KV v2 secrets
        engine, optionally retrieves a specific version.

        Args:
            path: Path to the secret (e.g., "myapp/config" or "secret/data/myapp/config")
            security_context: Security context with secrets.read permission
            version: Optional specific version to retrieve (KV v2 only)

        Returns:
            Dictionary containing the secret data

        Raises:
            AuthorizationError: If user lacks secrets.read permission
            SecretNotFoundError: If secret doesn't exist
            VaultConnectionError: If unable to connect to Vault
            SecretsError: For other Vault errors

        Example:
            ```python
            # Get latest version of a secret
            secret = await client.get_secret(
                path="myapp/database",
                security_context=context,
            )
            password = secret["password"]

            # Get specific version
            old_secret = await client.get_secret(
                path="myapp/database",
                security_context=context,
                version=2,
            )
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_READ, path)

        # Normalize path
        api_path = self._normalize_path(path)

        # Add version parameter if specified
        if version is not None:
            api_path = f"{api_path}?version={version}"

        logger.debug(
            "Getting secret from Vault",
            path=path,
            version=version,
            user_id=security_context.user_id,
        )

        try:
            response = await self._request("GET", api_path)

            # Extract data from KV v2 response format
            data = response.get("data", {})
            secret_data = data.get("data", {})

            # Audit success
            await self._audit_operation(
                action=AuditAction.READ,
                path=path,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "version": data.get("metadata", {}).get("version"),
                },
            )

            logger.info(
                "Secret retrieved successfully",
                path=path,
                user_id=security_context.user_id,
            )

            return secret_data

        except SecretNotFoundError:
            # Audit not found
            await self._audit_operation(
                action=AuditAction.READ,
                path=path,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"error": "not_found"},
            )
            raise
        except (AuthorizationError, AuthenticationError):
            # Audit access denied
            await self._audit_operation(
                action=AuditAction.READ,
                path=path,
                status=AuditStatus.DENIED,
                security_context=security_context,
            )
            raise
        except (SecretsError, VaultConnectionError, ConnectionError, TimeoutError, OSError, ValueError, TypeError, KeyError) as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.READ,
                path=path,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"error": str(e)},
            )
            raise

    async def set_secret(
        self,
        path: str,
        data: Dict[str, Any],
        security_context: SecurityContext,
        *,
        cas: Optional[int] = None,
    ) -> bool:
        """
        Set a secret in Vault.

        Creates or updates the secret at the specified path. For KV v2,
        this creates a new version of the secret.

        Args:
            path: Path to the secret (e.g., "myapp/config" or "secret/data/myapp/config")
            data: Secret data as key-value pairs
            security_context: Security context with secrets.write permission
            cas: Check-and-set value for optimistic locking (KV v2)

        Returns:
            True if the operation succeeded

        Raises:
            AuthorizationError: If user lacks secrets.write permission
            ValidationError: If data is invalid
            VaultConnectionError: If unable to connect to Vault
            SecretsError: For other Vault errors

        Example:
            ```python
            # Set a simple secret
            await client.set_secret(
                path="myapp/database",
                data={
                    "username": "dbuser",
                    "password": "secure-password-123",
                },
                security_context=context,
            )

            # Set with check-and-set (requires version match)
            await client.set_secret(
                path="myapp/config",
                data={"api_key": "new-key"},
                security_context=context,
                cas=3,  # Only succeeds if current version is 3
            )
            ```
        """
        # Validate input
        if not data:
            raise ValidationError(
                message="Secret data cannot be empty",
                suggestions=["Provide at least one key-value pair"],
            )

        # Check permission
        self._check_permission(security_context, self.PERMISSION_WRITE, path)

        # Normalize path
        api_path = self._normalize_path(path)

        # Build request body
        request_body: Dict[str, Any] = {"data": data}
        if cas is not None:
            request_body["options"] = {"cas": cas}

        logger.debug(
            "Setting secret in Vault",
            path=path,
            keys=list(data.keys()),
            user_id=security_context.user_id,
        )

        try:
            await self._request("POST", api_path, json_data=request_body)

            # Audit success
            await self._audit_operation(
                action=AuditAction.UPDATE,
                path=path,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "keys_updated": list(data.keys()),
                    "cas": cas,
                },
            )

            logger.info(
                "Secret set successfully",
                path=path,
                keys=list(data.keys()),
                user_id=security_context.user_id,
            )

            return True

        except (AuthorizationError, AuthenticationError):
            # Audit access denied
            await self._audit_operation(
                action=AuditAction.UPDATE,
                path=path,
                status=AuditStatus.DENIED,
                security_context=security_context,
            )
            raise
        except (SecretsError, VaultConnectionError, ConnectionError, TimeoutError, OSError, ValueError, TypeError, KeyError) as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.UPDATE,
                path=path,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"error": str(e)},
            )
            raise

    async def delete_secret(
        self,
        path: str,
        security_context: SecurityContext,
        *,
        versions: Optional[List[int]] = None,
        destroy: bool = False,
    ) -> bool:
        """
        Delete a secret from Vault.

        For KV v2, this performs a soft delete by default (can be undeleted).
        Use destroy=True for permanent deletion.

        Args:
            path: Path to the secret
            security_context: Security context with secrets.delete permission
            versions: Specific versions to delete (KV v2). If None, deletes latest.
            destroy: If True, permanently destroys the secret (cannot be recovered)

        Returns:
            True if the operation succeeded

        Raises:
            AuthorizationError: If user lacks secrets.delete permission
            SecretNotFoundError: If secret doesn't exist
            VaultConnectionError: If unable to connect to Vault
            SecretsError: For other Vault errors

        Example:
            ```python
            # Soft delete (can be undeleted)
            await client.delete_secret(
                path="myapp/old-config",
                security_context=context,
            )

            # Delete specific versions
            await client.delete_secret(
                path="myapp/config",
                security_context=context,
                versions=[1, 2, 3],
            )

            # Permanently destroy (cannot be recovered)
            await client.delete_secret(
                path="myapp/sensitive-data",
                security_context=context,
                destroy=True,
            )
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_DELETE, path)

        logger.debug(
            "Deleting secret from Vault",
            path=path,
            versions=versions,
            destroy=destroy,
            user_id=security_context.user_id,
        )

        try:
            if destroy:
                # Destroy endpoint for permanent deletion
                api_path = self._normalize_metadata_path(path).replace(
                    "/metadata/", "/destroy/"
                )
                request_body = {"versions": versions or []}
                await self._request("POST", api_path, json_data=request_body)
            elif versions:
                # Delete specific versions
                api_path = self._normalize_metadata_path(path).replace(
                    "/metadata/", "/delete/"
                )
                await self._request("POST", api_path, json_data={"versions": versions})
            else:
                # Delete latest version (soft delete)
                api_path = self._normalize_path(path)
                await self._request("DELETE", api_path)

            # Audit success
            await self._audit_operation(
                action=AuditAction.DELETE if not destroy else AuditAction.PURGE,
                path=path,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "versions": versions,
                    "destroy": destroy,
                },
            )

            logger.info(
                "Secret deleted successfully",
                path=path,
                destroy=destroy,
                user_id=security_context.user_id,
            )

            return True

        except SecretNotFoundError:
            # Audit not found
            await self._audit_operation(
                action=AuditAction.DELETE,
                path=path,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"error": "not_found"},
            )
            raise
        except (AuthorizationError, AuthenticationError):
            # Audit access denied
            await self._audit_operation(
                action=AuditAction.DELETE,
                path=path,
                status=AuditStatus.DENIED,
                security_context=security_context,
            )
            raise
        except (SecretsError, VaultConnectionError, ConnectionError, TimeoutError, OSError, ValueError, TypeError, KeyError) as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.DELETE,
                path=path,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"error": str(e)},
            )
            raise

    async def list_secrets(
        self,
        path: str,
        security_context: SecurityContext,
    ) -> List[str]:
        """
        List secrets at a path in Vault.

        Lists the keys at the specified path. Does not return secret values,
        only the names/keys.

        Args:
            path: Path to list (e.g., "myapp/" or "secret/metadata/myapp")
            security_context: Security context with secrets.list permission

        Returns:
            List of secret keys/names at the path

        Raises:
            AuthorizationError: If user lacks secrets.list permission
            SecretNotFoundError: If path doesn't exist
            VaultConnectionError: If unable to connect to Vault
            SecretsError: For other Vault errors

        Example:
            ```python
            # List all secrets in a namespace
            secrets = await client.list_secrets(
                path="myapp/",
                security_context=context,
            )
            # Returns: ["database", "api-keys", "config/"]

            # Paths ending with "/" indicate subdirectories
            for secret_name in secrets:
                if secret_name.endswith("/"):
                    print(f"Directory: {secret_name}")
                else:
                    print(f"Secret: {secret_name}")
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_LIST, path)

        # Normalize path for metadata operations
        api_path = self._normalize_metadata_path(path)

        logger.debug(
            "Listing secrets in Vault",
            path=path,
            user_id=security_context.user_id,
        )

        try:
            response = await self._request("LIST", api_path)

            # Extract keys from response
            data = response.get("data", {})
            keys = data.get("keys", [])

            # Audit success
            await self._audit_operation(
                action=AuditAction.READ,
                path=path,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "operation": "list",
                    "count": len(keys),
                },
            )

            logger.info(
                "Secrets listed successfully",
                path=path,
                count=len(keys),
                user_id=security_context.user_id,
            )

            return keys

        except SecretNotFoundError:
            # Path doesn't exist, return empty list
            await self._audit_operation(
                action=AuditAction.READ,
                path=path,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={"operation": "list", "count": 0},
            )
            return []
        except (AuthorizationError, AuthenticationError):
            # Audit access denied
            await self._audit_operation(
                action=AuditAction.READ,
                path=path,
                status=AuditStatus.DENIED,
                security_context=security_context,
                metadata={"operation": "list"},
            )
            raise
        except (SecretsError, VaultConnectionError, ConnectionError, TimeoutError, OSError, ValueError, TypeError, KeyError) as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.READ,
                path=path,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"operation": "list", "error": str(e)},
            )
            raise

    async def rotate_secret(
        self,
        path: str,
        security_context: SecurityContext,
        *,
        generator: Optional[str] = None,
        length: int = 32,
        include_special: bool = True,
    ) -> Dict[str, Any]:
        """
        Rotate a secret by generating a new value.

        Reads the existing secret, generates new values for specified keys
        or all keys, and writes back as a new version.

        Args:
            path: Path to the secret to rotate
            security_context: Security context with secrets.read and secrets.write permissions
            generator: Key to generate new value for. If None, rotates all keys.
            length: Length of generated secret values
            include_special: Whether to include special characters in generated values

        Returns:
            Dictionary containing the new secret data

        Raises:
            AuthorizationError: If user lacks required permissions
            SecretNotFoundError: If secret doesn't exist
            VaultConnectionError: If unable to connect to Vault
            SecretsError: For other Vault errors

        Example:
            ```python
            # Rotate all keys in a secret
            new_secret = await client.rotate_secret(
                path="myapp/database",
                security_context=context,
            )
            print(f"New password: {new_secret['password']}")

            # Rotate specific key only
            new_secret = await client.rotate_secret(
                path="myapp/api",
                security_context=context,
                generator="api_key",
                length=64,
            )
            ```
        """
        import secrets

        # Check both read and write permissions
        self._check_permission(security_context, self.PERMISSION_READ, path)
        self._check_permission(security_context, self.PERMISSION_WRITE, path)

        logger.debug(
            "Rotating secret in Vault",
            path=path,
            generator=generator,
            user_id=security_context.user_id,
        )

        try:
            # Get current secret
            current_data = await self.get_secret(path, security_context)

            # Generate new values
            def generate_value() -> str:
                """Generate a secure random value."""
                if include_special:
                    alphabet = (
                        "abcdefghijklmnopqrstuvwxyz"
                        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                        "0123456789"
                        "!@#$%^&*()_+-=[]{}|;:,.<>?"
                    )
                else:
                    alphabet = (
                        "abcdefghijklmnopqrstuvwxyz"
                        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                        "0123456789"
                    )
                return "".join(secrets.choice(alphabet) for _ in range(length))

            # Update values
            new_data = current_data.copy()
            rotated_keys = []

            if generator:
                # Rotate specific key
                if generator in new_data:
                    new_data[generator] = generate_value()
                    rotated_keys.append(generator)
                else:
                    raise ValidationError(
                        message=f"Key '{generator}' not found in secret",
                        suggestions=[f"Available keys: {list(current_data.keys())}"],
                    )
            else:
                # Rotate all string values
                for key, value in current_data.items():
                    if isinstance(value, str):
                        new_data[key] = generate_value()
                        rotated_keys.append(key)

            # Write new version
            await self.set_secret(path, new_data, security_context)

            # Audit rotation
            await self._audit_operation(
                action=AuditAction.UPDATE,
                path=path,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "operation": "rotate",
                    "rotated_keys": rotated_keys,
                },
            )

            logger.info(
                "Secret rotated successfully",
                path=path,
                rotated_keys=rotated_keys,
                user_id=security_context.user_id,
            )

            return new_data

        except (SecretsError, AuthorizationError, SecretNotFoundError, VaultConnectionError, ValidationError) as e:
            # Audit failure (if not already audited by get/set)
            if not isinstance(e, (AuthorizationError, SecretNotFoundError)):
                await self._audit_operation(
                    action=AuditAction.UPDATE,
                    path=path,
                    status=AuditStatus.FAILURE,
                    security_context=security_context,
                    metadata={"operation": "rotate", "error": str(e)},
                )
            raise
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError, KeyError) as e:
            await self._audit_operation(
                action=AuditAction.UPDATE,
                path=path,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"operation": "rotate", "error": str(e)},
            )
            raise

    async def get_secret_metadata(
        self,
        path: str,
        security_context: SecurityContext,
    ) -> SecretMetadata:
        """
        Get metadata for a secret.

        Retrieves metadata about the secret including version history
        and custom metadata. Does not return secret values.

        Args:
            path: Path to the secret
            security_context: Security context with secrets.read permission

        Returns:
            SecretMetadata object with version information

        Raises:
            AuthorizationError: If user lacks secrets.read permission
            SecretNotFoundError: If secret doesn't exist
            VaultConnectionError: If unable to connect to Vault
            SecretsError: For other Vault errors

        Example:
            ```python
            metadata = await client.get_secret_metadata(
                path="myapp/database",
                security_context=context,
            )
            print(f"Current version: {metadata.version}")
            print(f"Created: {metadata.created_time}")
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_READ, path)

        # Use metadata endpoint
        api_path = self._normalize_metadata_path(path)

        logger.debug(
            "Getting secret metadata from Vault",
            path=path,
            user_id=security_context.user_id,
        )

        try:
            response = await self._request("GET", api_path)

            data = response.get("data", {})

            # Parse metadata
            metadata = SecretMetadata(
                version=data.get("current_version", 0),
                custom_metadata=data.get("custom_metadata", {}),
            )

            # Parse version-specific metadata if available
            versions = data.get("versions", {})
            if versions and str(metadata.version) in versions:
                version_data = versions[str(metadata.version)]
                if version_data.get("created_time"):
                    try:
                        metadata.created_time = datetime.fromisoformat(
                            version_data["created_time"].replace("Z", "+00:00")
                        )
                    except (ValueError, KeyError):
                        pass
                metadata.destroyed = version_data.get("destroyed", False)

            logger.info(
                "Secret metadata retrieved successfully",
                path=path,
                version=metadata.version,
                user_id=security_context.user_id,
            )

            return metadata

        except SecretNotFoundError:
            raise
        except (SecretsError, VaultConnectionError, AuthorizationError, AuthenticationError, ConnectionError, TimeoutError, OSError, ValueError, TypeError, KeyError) as e:
            logger.error(
                "Failed to get secret metadata",
                exc_info=e,
                path=path,
            )
            raise

    async def close(self) -> None:
        """
        Close the Vault client and clean up resources.

        Should be called when done using the client to properly
        close HTTP connections.

        Example:
            ```python
            client = VaultClient(config)
            try:
                secret = await client.get_secret("myapp/config", context)
            finally:
                await client.close()

            # Or use as async context manager (recommended)
            async with VaultClient(config) as client:
                secret = await client.get_secret("myapp/config", context)
            ```
        """
        if self._session:
            await self._session.close()
            self._session = None
            logger.debug("Vault client session closed")

    async def __aenter__(self) -> "VaultClient":
        """Enter async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[Exception],
        exc_tb: Any,
    ) -> None:
        """Exit async context manager."""
        await self.close()

    async def health_check(self) -> bool:
        """
        Check if Vault is healthy and accessible.

        Performs a health check against the Vault server to verify
        connectivity and server status.

        Returns:
            True if Vault is healthy, False otherwise

        Example:
            ```python
            is_healthy = await client.health_check()
            if not is_healthy:
                logger.warning("Vault is not healthy")
            ```
        """
        try:
            session = await self._ensure_session()
            url = urljoin(self._config.url + "/", "/v1/sys/health")

            async with session.get(url, headers=self._build_headers()) as response:
                # Vault returns different status codes for different states
                # 200 = initialized, unsealed, active
                # 429 = unsealed, standby
                # 472 = DR secondary
                # 473 = performance standby
                # 501 = not initialized
                # 503 = sealed
                return response.status in (200, 429, 472, 473)

        except (ConnectionError, TimeoutError, OSError, AgenticBaseException) as e:
            logger.warning("Vault health check failed", exc_info=e)
            return False
