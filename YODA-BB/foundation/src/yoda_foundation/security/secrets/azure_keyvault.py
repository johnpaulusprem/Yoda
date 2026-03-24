"""
Azure Key Vault client for the Agentic AI Component Library.

This module provides a secure, async client for interacting with Azure Key Vault
for secrets management. It handles authentication, secret operations, and
integrates with the library's security context and audit logging.

Example:
    ```python
    from yoda_foundation.security.secrets import (
        AzureKeyVaultClient,
        AzureKeyVaultConfig,
    )
    from yoda_foundation.security import create_security_context

    # Configure Azure Key Vault client
    config = AzureKeyVaultConfig(
        vault_url="https://my-vault.vault.azure.net/",
        tenant_id="your-tenant-id",
        client_id="your-client-id",
        client_secret="your-client-secret",
    )

    # Create client
    client = AzureKeyVaultClient(config)

    # Create security context
    context = create_security_context(
        user_id="user_123",
        permissions=["secrets.read", "secrets.write", "secrets.list"],
    )

    # Get a secret
    secret = await client.get_secret(
        name="myapp-database-password",
        security_context=context,
    )

    # Set a secret
    result = await client.set_secret(
        name="myapp-api-key",
        value="secret-value",
        security_context=context,
        content_type="application/json",
        tags={"environment": "production"},
    )

    # List secrets
    secrets = await client.list_secrets(
        security_context=context,
        max_results=100,
    )

    # Delete a secret (soft delete)
    await client.delete_secret(
        name="myapp-old-config",
        security_context=context,
    )

    # Purge a deleted secret (permanent deletion)
    await client.purge_deleted_secret(
        name="myapp-old-config",
        security_context=context,
    )

    # Recover a deleted secret
    result = await client.recover_deleted_secret(
        name="myapp-accidentally-deleted",
        security_context=context,
    )

    # Backup a secret
    backup_data = await client.backup_secret(
        name="myapp-critical-secret",
        security_context=context,
    )

    # Restore a secret from backup
    result = await client.restore_secret(
        backup=backup_data,
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from yoda_foundation.security.context import SecurityContext
from yoda_foundation.security.data_governance.audit_logger import (
    AuditLogger,
    AuditAction,
    AuditStatus,
)
from yoda_foundation.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ValidationError,
)
from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)
from yoda_foundation.observability.logging import get_logger

try:
    from azure.core.exceptions import (
        AzureError as _AzureError,
    )
except ImportError:
    _AzureError = None  # type: ignore[assignment, misc]

# Build combined exception tuple for Azure operation catch blocks
_AZURE_OPERATION_ERRORS: tuple = tuple(
    e for e in (
        _AzureError,
        ConnectionError, TimeoutError, OSError,
        ValueError, TypeError, KeyError,
    ) if e is not None
)

logger = get_logger(__name__)


# =============================================================================
# Azure Key Vault-Specific Exceptions
# =============================================================================


class AzureKeyVaultError(AgenticBaseException):
    """
    Base exception for Azure Key Vault errors.

    Provides common attributes for Azure Key Vault-related operations.

    Attributes:
        secret_name: Name of the secret
        operation: The operation that failed

    Example:
        ```python
        raise AzureKeyVaultError(
            message="Secret operation failed",
            secret_name="myapp-config",
            operation="read",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Azure Key Vault operation failed",
        *,
        secret_name: Optional[str] = None,
        operation: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
        severity: ErrorSeverity = ErrorSeverity.HIGH,
        retryable: bool = False,
    ) -> None:
        """
        Initialize Azure Key Vault error.

        Args:
            message: Human-readable error description
            secret_name: Name of the secret
            operation: The operation that failed
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
            severity: Error severity level
            retryable: Whether the operation can be retried
        """
        self.secret_name = secret_name
        self.operation = operation

        extra_details = {
            "secret_name": secret_name,
            "operation": operation,
        }

        merged_details = {**extra_details, **(details or {})}

        super().__init__(
            message=message,
            category=ErrorCategory.RESOURCE,
            severity=severity,
            retryable=retryable,
            user_message="An Azure Key Vault operation failed. Please try again.",
            suggestions=suggestions or [
                "Check Azure connectivity and credentials",
                "Verify your Azure RBAC permissions",
                "Ensure the secret name is correct",
            ],
            cause=cause,
            details=merged_details,
        )


class AzureKeyVaultConnectionError(AzureKeyVaultError):
    """
    Azure Key Vault connection error.

    Raised when unable to connect to Azure Key Vault.

    Example:
        ```python
        raise AzureKeyVaultConnectionError(
            vault_url="https://my-vault.vault.azure.net/",
            cause=original_error,
        )
        ```
    """

    def __init__(
        self,
        message: str = "Failed to connect to Azure Key Vault",
        *,
        vault_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        suggestions: Optional[List[str]] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize Azure Key Vault connection error.

        Args:
            message: Human-readable error description
            vault_url: The vault URL that failed
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
            "Check Azure credentials configuration",
            "Verify network connectivity to Azure",
            "Check Azure Active Directory permissions",
        ]
        if timeout_seconds:
            default_suggestions.append(
                f"Consider increasing timeout from {timeout_seconds}s"
            )

        super().__init__(
            message=message,
            operation="connect",
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=merged_details,
            severity=ErrorSeverity.HIGH,
            retryable=True,
        )
        self.user_message = (
            "Unable to connect to Azure Key Vault. Please try again later."
        )


class AzureSecretNotFoundError(AzureKeyVaultError):
    """
    Azure secret not found error.

    Raised when a requested secret does not exist in Azure Key Vault.

    Example:
        ```python
        raise AzureSecretNotFoundError(
            secret_name="myapp-missing-secret",
        )
        ```
    """

    def __init__(
        self,
        message: str = "",
        *,
        secret_name: str,
        version: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize secret not found error.

        Args:
            message: Human-readable error description
            secret_name: Name of the missing secret
            version: Version of the secret requested
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        if not message:
            if version:
                message = f"Secret not found: '{secret_name}' version '{version}'"
            else:
                message = f"Secret not found: '{secret_name}'"

        self.version = version

        extra_details = {"version": version}
        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "Verify the secret name is correct",
            "Check if the secret has been deleted",
            "Ensure you have read permissions for this secret",
        ]

        super().__init__(
            message=message,
            secret_name=secret_name,
            operation="read",
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=merged_details,
            severity=ErrorSeverity.LOW,
            retryable=False,
        )
        self.user_message = "The requested secret was not found."


class AzureSecretAccessDeniedError(AzureKeyVaultError):
    """
    Azure secret access denied error.

    Raised when access to a secret is denied due to insufficient permissions.

    Example:
        ```python
        raise AzureSecretAccessDeniedError(
            secret_name="admin-config",
            required_permission="secrets.read",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Access denied to secret",
        *,
        secret_name: str,
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
            secret_name: Name of the secret
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
            "Verify your Azure RBAC role assignments",
            "Check Key Vault access policies",
        ]
        if required_permission:
            default_suggestions.insert(
                0, f"Request the '{required_permission}' permission"
            )

        super().__init__(
            message=message,
            secret_name=secret_name,
            operation=operation,
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=merged_details,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
        )
        self.user_message = "You don't have permission to access this secret."


class AzureSecretDeletedError(AzureKeyVaultError):
    """
    Azure secret is in deleted state error.

    Raised when trying to access a secret that has been soft-deleted.

    Example:
        ```python
        raise AzureSecretDeletedError(
            secret_name="myapp-deleted-secret",
        )
        ```
    """

    def __init__(
        self,
        message: str = "",
        *,
        secret_name: str,
        scheduled_purge_date: Optional[datetime] = None,
        suggestions: Optional[List[str]] = None,
        cause: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize secret deleted error.

        Args:
            message: Human-readable error description
            secret_name: Name of the deleted secret
            scheduled_purge_date: When the secret will be permanently purged
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        if not message:
            message = f"Secret '{secret_name}' is in deleted state"

        self.scheduled_purge_date = scheduled_purge_date

        extra_details = {
            "scheduled_purge_date": (
                scheduled_purge_date.isoformat() if scheduled_purge_date else None
            ),
        }
        merged_details = {**extra_details, **(details or {})}

        default_suggestions = [
            "Use recover_deleted_secret to restore the secret",
            "Use purge_deleted_secret to permanently delete the secret",
        ]

        super().__init__(
            message=message,
            secret_name=secret_name,
            operation="access",
            suggestions=suggestions or default_suggestions,
            cause=cause,
            details=merged_details,
            severity=ErrorSeverity.MEDIUM,
            retryable=False,
        )
        self.user_message = "The requested secret has been deleted."


# =============================================================================
# Configuration and Data Classes
# =============================================================================


@dataclass
class AzureKeyVaultConfig:
    """
    Configuration for Azure Key Vault client.

    Holds all configuration needed to connect to and authenticate
    with Azure Key Vault.

    Attributes:
        vault_url: Azure Key Vault URL (e.g., "https://my-vault.vault.azure.net/")
        credential: Azure credential object (optional, uses DefaultAzureCredential if not provided)
        tenant_id: Azure AD tenant ID (for service principal authentication)
        client_id: Azure AD application (client) ID (for service principal authentication)
        client_secret: Azure AD application secret (for service principal authentication)
        timeout: Request timeout in seconds

    Example:
        ```python
        # Using explicit service principal credentials
        config = AzureKeyVaultConfig(
            vault_url="https://my-vault.vault.azure.net/",
            tenant_id="your-tenant-id",
            client_id="your-client-id",
            client_secret="your-client-secret",
        )

        # Using DefaultAzureCredential (recommended for production)
        config = AzureKeyVaultConfig(
            vault_url="https://my-vault.vault.azure.net/",
        )

        # Using custom credential object
        from azure.identity.aio import ManagedIdentityCredential
        credential = ManagedIdentityCredential()
        config = AzureKeyVaultConfig(
            vault_url="https://my-vault.vault.azure.net/",
            credential=credential,
        )
        ```
    """

    vault_url: str
    credential: Optional[Any] = None
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    timeout: float = 30.0

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not self.vault_url:
            raise ValidationError(
                message="Azure Key Vault URL is required",
                suggestions=["Provide a valid vault URL (e.g., 'https://my-vault.vault.azure.net/')"],
            )

        # Ensure URL doesn't have trailing slash for consistency
        self.vault_url = self.vault_url.rstrip("/")

        # Validate service principal authentication
        if self.client_id and not (self.tenant_id and self.client_secret):
            raise ValidationError(
                message="tenant_id and client_secret are required when client_id is provided",
                suggestions=["Provide tenant_id, client_id, and client_secret together"],
            )

        if self.client_secret and not (self.tenant_id and self.client_id):
            raise ValidationError(
                message="tenant_id and client_id are required when client_secret is provided",
                suggestions=["Provide tenant_id, client_id, and client_secret together"],
            )


@dataclass
class AzureSecretMetadata:
    """
    Metadata for a secret in Azure Key Vault.

    Contains information about the secret's versioning and lifecycle.

    Attributes:
        name: Secret name
        vault_url: URL of the vault containing the secret
        version: Secret version
        enabled: Whether the secret is enabled
        created_on: When the secret was created
        updated_on: When the secret was last updated
        not_before: Secret is not valid before this time
        expires_on: Secret expiration time
        content_type: Content type hint for the secret value
        tags: User-defined tags
        recovery_level: Recovery level of the secret
        recoverable_days: Days until permanent deletion

    Example:
        ```python
        metadata = AzureSecretMetadata(
            name="myapp-config",
            vault_url="https://my-vault.vault.azure.net",
            version="abc123",
            enabled=True,
            created_on=datetime.now(timezone.utc),
            content_type="application/json",
        )
        ```
    """

    name: str
    vault_url: str
    version: Optional[str] = None
    enabled: bool = True
    created_on: Optional[datetime] = None
    updated_on: Optional[datetime] = None
    not_before: Optional[datetime] = None
    expires_on: Optional[datetime] = None
    content_type: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    recovery_level: Optional[str] = None
    recoverable_days: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "name": self.name,
            "vault_url": self.vault_url,
            "version": self.version,
            "enabled": self.enabled,
            "created_on": (
                self.created_on.isoformat() if self.created_on else None
            ),
            "updated_on": (
                self.updated_on.isoformat() if self.updated_on else None
            ),
            "not_before": (
                self.not_before.isoformat() if self.not_before else None
            ),
            "expires_on": (
                self.expires_on.isoformat() if self.expires_on else None
            ),
            "content_type": self.content_type,
            "tags": self.tags,
            "recovery_level": self.recovery_level,
            "recoverable_days": self.recoverable_days,
        }


# =============================================================================
# Azure Key Vault Client Implementation
# =============================================================================


class AzureKeyVaultClient:
    """
    Async Azure Key Vault client for secrets management.

    Provides secure, audited access to secrets stored in Azure Key Vault.
    Integrates with the library's security context and audit logging.

    Attributes:
        config: Azure Key Vault configuration
        audit_logger: Optional audit logger for tracking secret operations

    Example:
        ```python
        from yoda_foundation.security.secrets import (
            AzureKeyVaultClient,
            AzureKeyVaultConfig,
        )
        from yoda_foundation.security import create_security_context

        # Create configuration
        config = AzureKeyVaultConfig(
            vault_url="https://my-vault.vault.azure.net/",
            tenant_id="your-tenant-id",
            client_id="your-client-id",
            client_secret="your-client-secret",
        )

        # Create client
        client = AzureKeyVaultClient(config)

        # Create security context with appropriate permissions
        context = create_security_context(
            user_id="user_123",
            permissions=["secrets.read", "secrets.write", "secrets.list", "secrets.delete"],
        )

        # Read a secret
        secret = await client.get_secret(
            name="myapp-database-password",
            security_context=context,
        )
        print(f"Secret value: {secret['value']}")

        # Create/update a secret
        result = await client.set_secret(
            name="myapp-api-key",
            value="my-secret-value",
            security_context=context,
            content_type="text/plain",
            tags={"environment": "production"},
        )

        # List secrets
        secrets = await client.list_secrets(
            security_context=context,
        )
        for secret in secrets:
            print(f"Name: {secret['name']}")

        # Delete a secret (soft delete)
        await client.delete_secret(
            name="myapp-old-config",
            security_context=context,
        )

        # Recover a deleted secret
        result = await client.recover_deleted_secret(
            name="myapp-old-config",
            security_context=context,
        )

        # Backup and restore
        backup = await client.backup_secret("myapp-critical", context)
        result = await client.restore_secret(backup, context)

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
        config: AzureKeyVaultConfig,
        audit_logger: Optional[AuditLogger] = None,
    ) -> None:
        """
        Initialize Azure Key Vault client.

        Args:
            config: Azure Key Vault configuration
            audit_logger: Optional audit logger for tracking operations

        Example:
            ```python
            config = AzureKeyVaultConfig(
                vault_url="https://my-vault.vault.azure.net/",
                tenant_id="your-tenant-id",
                client_id="your-client-id",
                client_secret="your-client-secret",
            )

            # With audit logging
            audit = AuditLogger()
            client = AzureKeyVaultClient(config, audit_logger=audit)

            # Without audit logging
            client = AzureKeyVaultClient(config)
            ```
        """
        self._config = config
        self._audit_logger = audit_logger
        self._client: Optional[Any] = None
        self._credential: Optional[Any] = None
        self._lock = asyncio.Lock()

    @property
    def config(self) -> AzureKeyVaultConfig:
        """Get the Azure Key Vault configuration."""
        return self._config

    async def _ensure_client(self) -> Any:
        """
        Ensure an Azure Key Vault SecretClient is available.

        Creates a new client if one doesn't exist.

        Returns:
            Azure SecretClient

        Raises:
            AzureKeyVaultConnectionError: If unable to create client
        """
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    try:
                        from azure.keyvault.secrets.aio import SecretClient

                        # Get or create credential
                        credential = await self._get_credential()

                        # Create the client
                        self._client = SecretClient(
                            vault_url=self._config.vault_url,
                            credential=credential,
                        )

                    except ImportError as e:
                        raise AzureKeyVaultConnectionError(
                            message="azure-keyvault-secrets and azure-identity are required for Azure Key Vault client",
                            vault_url=self._config.vault_url,
                            cause=e,
                            suggestions=[
                                "Install azure-keyvault-secrets: pip install azure-keyvault-secrets",
                                "Install azure-identity: pip install azure-identity",
                            ],
                        )
                    except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
                        raise AzureKeyVaultConnectionError(
                            message=f"Failed to create Azure Key Vault client: {e}",
                            vault_url=self._config.vault_url,
                            cause=e,
                        )

        return self._client

    async def _get_credential(self) -> Any:
        """
        Get or create Azure credential.

        Returns the configured credential or creates a new one based on
        configuration.

        Returns:
            Azure credential object

        Raises:
            AzureKeyVaultConnectionError: If unable to create credential
        """
        if self._credential is not None:
            return self._credential

        # Use provided credential if available
        if self._config.credential is not None:
            self._credential = self._config.credential
            return self._credential

        try:
            # Use service principal if credentials provided
            if self._config.tenant_id and self._config.client_id and self._config.client_secret:
                from azure.identity.aio import ClientSecretCredential

                self._credential = ClientSecretCredential(
                    tenant_id=self._config.tenant_id,
                    client_id=self._config.client_id,
                    client_secret=self._config.client_secret,
                )
            else:
                # Use default credential chain
                from azure.identity.aio import DefaultAzureCredential

                self._credential = DefaultAzureCredential()

            return self._credential

        except ImportError as e:
            raise AzureKeyVaultConnectionError(
                message="azure-identity is required for Azure authentication",
                vault_url=self._config.vault_url,
                cause=e,
                suggestions=["Install azure-identity: pip install azure-identity"],
            )
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            raise AzureKeyVaultConnectionError(
                message=f"Failed to create Azure credential: {e}",
                vault_url=self._config.vault_url,
                cause=e,
            )

    def _check_permission(
        self,
        security_context: SecurityContext,
        permission: str,
        secret_name: str,
    ) -> None:
        """
        Check if security context has required permission.

        Args:
            security_context: Security context to check
            permission: Required permission
            secret_name: Secret name being accessed

        Raises:
            AuthorizationError: If permission not granted
        """
        if not security_context.has_permission(permission):
            raise AuthorizationError(
                message=f"Permission denied: {permission}",
                required_permission=permission,
                resource=f"azure-secret:{secret_name}",
                user_id=security_context.user_id,
            )

    async def _audit_operation(
        self,
        action: AuditAction,
        secret_name: str,
        status: AuditStatus,
        security_context: SecurityContext,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Audit a secret operation.

        Args:
            action: The audit action
            secret_name: Secret name
            status: Operation status
            security_context: Security context
            metadata: Additional metadata
        """
        if self._audit_logger:
            try:
                await self._audit_logger.log(
                    action=action,
                    resource_type="azure-secret",
                    resource_id=secret_name,
                    status=status,
                    security_context=security_context,
                    metadata=metadata or {},
                )
            except (AgenticBaseException, ConnectionError, TimeoutError, OSError) as e:
                # Log error but don't fail the operation
                logger.warning(
                    "Failed to write Azure Key Vault audit entry",
                    exc_info=e,
                    secret_name=secret_name,
                    action=action.value,
                )

    def _handle_azure_error(
        self,
        error: Exception,
        secret_name: str,
        operation: str,
    ) -> None:
        """
        Handle Azure SDK errors and convert to library exceptions.

        Args:
            error: The Azure SDK error
            secret_name: Secret name involved
            operation: Operation that failed

        Raises:
            AzureSecretNotFoundError: If secret not found
            AzureSecretAccessDeniedError: If access denied
            AzureSecretDeletedError: If secret is deleted
            AzureKeyVaultConnectionError: If connection failed
            AzureKeyVaultError: For other errors
        """
        from azure.core.exceptions import (
            ResourceNotFoundError,
            HttpResponseError,
            ClientAuthenticationError,
            ServiceRequestError,
        )

        if isinstance(error, ResourceNotFoundError):
            raise AzureSecretNotFoundError(
                secret_name=secret_name,
                cause=error,
            )

        if isinstance(error, ClientAuthenticationError):
            raise AzureKeyVaultConnectionError(
                message=f"Azure authentication failed: {error}",
                vault_url=self._config.vault_url,
                cause=error,
                suggestions=[
                    "Check Azure credentials",
                    "Verify service principal permissions",
                    "Ensure tenant ID is correct",
                ],
            )

        if isinstance(error, ServiceRequestError):
            raise AzureKeyVaultConnectionError(
                message=f"Azure Key Vault connection failed: {error}",
                vault_url=self._config.vault_url,
                cause=error,
            )

        if isinstance(error, HttpResponseError):
            # Check for specific HTTP status codes
            status_code = getattr(error, "status_code", None)

            if status_code == 403:
                raise AzureSecretAccessDeniedError(
                    message=f"Access denied to secret: {error}",
                    secret_name=secret_name,
                    operation=operation,
                    cause=error,
                )

            if status_code == 404:
                raise AzureSecretNotFoundError(
                    secret_name=secret_name,
                    cause=error,
                )

            if status_code == 409:
                # Conflict - often means secret is in deleted state
                error_message = str(error).lower()
                if "deleted" in error_message or "recovery" in error_message:
                    raise AzureSecretDeletedError(
                        secret_name=secret_name,
                        cause=error,
                    )

        # Generic error
        raise AzureKeyVaultError(
            message=f"Azure Key Vault operation failed: {error}",
            secret_name=secret_name,
            operation=operation,
            cause=error,
            retryable=True,
        )

    async def get_secret(
        self,
        name: str,
        security_context: SecurityContext,
        *,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a secret from Azure Key Vault.

        Retrieves the secret value at the specified name. Optionally
        retrieves a specific version.

        Args:
            name: Name of the secret
            security_context: Security context with secrets.read permission
            version: Optional specific version to retrieve

        Returns:
            Dictionary containing the secret data with keys:
            - value: The secret value
            - name: Secret name
            - version: Secret version
            - content_type: Content type (if set)
            - enabled: Whether the secret is enabled
            - created_on: Creation timestamp
            - updated_on: Last update timestamp
            - expires_on: Expiration timestamp (if set)
            - not_before: Not before timestamp (if set)
            - tags: Secret tags

        Raises:
            AuthorizationError: If user lacks secrets.read permission
            AzureSecretNotFoundError: If secret doesn't exist
            AzureKeyVaultConnectionError: If unable to connect to Azure
            AzureKeyVaultError: For other Azure errors

        Example:
            ```python
            # Get latest version of a secret
            secret = await client.get_secret(
                name="myapp-database-password",
                security_context=context,
            )
            password = secret["value"]

            # Get specific version
            old_secret = await client.get_secret(
                name="myapp-database-password",
                security_context=context,
                version="abc123def456",
            )
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_READ, name)

        logger.debug(
            "Getting secret from Azure Key Vault",
            secret_name=name,
            version=version,
            user_id=security_context.user_id,
        )

        try:
            client = await self._ensure_client()

            # Get the secret
            secret = await client.get_secret(name, version=version)

            # Build response dictionary
            result = {
                "value": secret.value,
                "name": secret.name,
                "version": secret.properties.version,
                "content_type": secret.properties.content_type,
                "enabled": secret.properties.enabled,
                "created_on": secret.properties.created_on,
                "updated_on": secret.properties.updated_on,
                "expires_on": secret.properties.expires_on,
                "not_before": secret.properties.not_before,
                "tags": secret.properties.tags or {},
            }

            # Audit success
            await self._audit_operation(
                action=AuditAction.READ,
                secret_name=name,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "version": secret.properties.version,
                },
            )

            logger.info(
                "Secret retrieved successfully",
                secret_name=name,
                user_id=security_context.user_id,
            )

            return result

        except (AuthorizationError, AzureKeyVaultError):
            raise
        except _AZURE_OPERATION_ERRORS as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.READ,
                secret_name=name,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"error": str(e)},
            )
            self._handle_azure_error(e, name, "read")
            raise  # This line won't be reached but helps with type checking

    async def set_secret(
        self,
        name: str,
        value: str,
        security_context: SecurityContext,
        *,
        content_type: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        enabled: bool = True,
        expires_on: Optional[datetime] = None,
        not_before: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Set a secret in Azure Key Vault.

        Creates or updates the secret at the specified name. This creates
        a new version of the secret.

        Args:
            name: Name of the secret
            value: Secret value
            security_context: Security context with secrets.write permission
            content_type: Content type hint for the secret value (e.g., "application/json")
            tags: User-defined tags (max 15 tags)
            enabled: Whether the secret is enabled (default True)
            expires_on: Optional expiration time (UTC)
            not_before: Optional not-before time (UTC)

        Returns:
            Dictionary containing the created secret metadata with keys:
            - name: Secret name
            - version: New secret version
            - content_type: Content type (if set)
            - enabled: Whether the secret is enabled
            - created_on: Creation timestamp
            - updated_on: Last update timestamp
            - expires_on: Expiration timestamp (if set)
            - not_before: Not before timestamp (if set)
            - tags: Secret tags

        Raises:
            AuthorizationError: If user lacks secrets.write permission
            ValidationError: If inputs are invalid
            AzureKeyVaultConnectionError: If unable to connect to Azure
            AzureKeyVaultError: For other Azure errors

        Example:
            ```python
            # Set a simple secret
            result = await client.set_secret(
                name="myapp-api-key",
                value="my-secret-value",
                security_context=context,
            )

            # Set with metadata
            result = await client.set_secret(
                name="myapp-database-password",
                value="secure-password-123",
                security_context=context,
                content_type="text/plain",
                tags={"environment": "production", "team": "backend"},
                expires_on=datetime(2025, 12, 31, tzinfo=timezone.utc),
            )
            ```
        """
        # Validate input
        if not name:
            raise ValidationError(
                message="Secret name cannot be empty",
                suggestions=["Provide a valid secret name"],
            )

        if not value:
            raise ValidationError(
                message="Secret value cannot be empty",
                suggestions=["Provide a non-empty secret value"],
            )

        # Check permission
        self._check_permission(security_context, self.PERMISSION_WRITE, name)

        logger.debug(
            "Setting secret in Azure Key Vault",
            secret_name=name,
            user_id=security_context.user_id,
        )

        try:
            client = await self._ensure_client()

            # Set the secret
            secret = await client.set_secret(
                name,
                value,
                content_type=content_type,
                tags=tags,
                enabled=enabled,
                expires_on=expires_on,
                not_before=not_before,
            )

            # Build response dictionary
            result = {
                "name": secret.name,
                "version": secret.properties.version,
                "content_type": secret.properties.content_type,
                "enabled": secret.properties.enabled,
                "created_on": secret.properties.created_on,
                "updated_on": secret.properties.updated_on,
                "expires_on": secret.properties.expires_on,
                "not_before": secret.properties.not_before,
                "tags": secret.properties.tags or {},
            }

            # Audit success
            await self._audit_operation(
                action=AuditAction.UPDATE,
                secret_name=name,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "version": secret.properties.version,
                    "has_content_type": content_type is not None,
                    "has_tags": tags is not None,
                    "has_expiration": expires_on is not None,
                },
            )

            logger.info(
                "Secret set successfully",
                secret_name=name,
                version=secret.properties.version,
                user_id=security_context.user_id,
            )

            return result

        except (AuthorizationError, ValidationError, AzureKeyVaultError):
            raise
        except _AZURE_OPERATION_ERRORS as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.UPDATE,
                secret_name=name,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"error": str(e)},
            )
            self._handle_azure_error(e, name, "write")
            raise

    async def delete_secret(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Delete a secret from Azure Key Vault.

        Performs a soft delete of the secret. The secret can be recovered
        using recover_deleted_secret until the retention period expires.

        Args:
            name: Name of the secret to delete
            security_context: Security context with secrets.delete permission

        Returns:
            True if the operation succeeded

        Raises:
            AuthorizationError: If user lacks secrets.delete permission
            AzureSecretNotFoundError: If secret doesn't exist
            AzureKeyVaultConnectionError: If unable to connect to Azure
            AzureKeyVaultError: For other Azure errors

        Example:
            ```python
            # Soft delete a secret
            await client.delete_secret(
                name="myapp-old-config",
                security_context=context,
            )

            # The secret can still be recovered
            await client.recover_deleted_secret(
                name="myapp-old-config",
                security_context=context,
            )
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_DELETE, name)

        logger.debug(
            "Deleting secret from Azure Key Vault",
            secret_name=name,
            user_id=security_context.user_id,
        )

        try:
            client = await self._ensure_client()

            # Begin the delete operation
            poller = await client.begin_delete_secret(name)

            # Wait for completion
            await poller.wait()

            # Audit success
            await self._audit_operation(
                action=AuditAction.DELETE,
                secret_name=name,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
            )

            logger.info(
                "Secret deleted successfully",
                secret_name=name,
                user_id=security_context.user_id,
            )

            return True

        except (AuthorizationError, AzureKeyVaultError):
            raise
        except _AZURE_OPERATION_ERRORS as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.DELETE,
                secret_name=name,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"error": str(e)},
            )
            self._handle_azure_error(e, name, "delete")
            raise

    async def list_secrets(
        self,
        security_context: SecurityContext,
        *,
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        List secrets in Azure Key Vault.

        Retrieves a list of secrets with their metadata. Does not return
        secret values, only names and properties.

        Args:
            security_context: Security context with secrets.list permission
            max_results: Maximum number of secrets to return (None for all)

        Returns:
            List of secret metadata dictionaries with keys:
            - name: Secret name
            - version: Current secret version
            - enabled: Whether the secret is enabled
            - created_on: Creation timestamp
            - updated_on: Last update timestamp
            - expires_on: Expiration timestamp (if set)
            - content_type: Content type (if set)
            - tags: Secret tags

        Raises:
            AuthorizationError: If user lacks secrets.list permission
            AzureKeyVaultConnectionError: If unable to connect to Azure
            AzureKeyVaultError: For other Azure errors

        Example:
            ```python
            # List all secrets
            secrets = await client.list_secrets(
                security_context=context,
            )
            for secret in secrets:
                print(f"Name: {secret['name']}, Enabled: {secret['enabled']}")

            # List with limit
            secrets = await client.list_secrets(
                security_context=context,
                max_results=10,
            )
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_LIST, "*")

        logger.debug(
            "Listing secrets in Azure Key Vault",
            max_results=max_results,
            user_id=security_context.user_id,
        )

        try:
            client = await self._ensure_client()

            secrets: List[Dict[str, Any]] = []

            # List secrets
            async for secret_properties in client.list_properties_of_secrets():
                secrets.append({
                    "name": secret_properties.name,
                    "version": secret_properties.version,
                    "enabled": secret_properties.enabled,
                    "created_on": secret_properties.created_on,
                    "updated_on": secret_properties.updated_on,
                    "expires_on": secret_properties.expires_on,
                    "content_type": secret_properties.content_type,
                    "tags": secret_properties.tags or {},
                })

                if max_results and len(secrets) >= max_results:
                    break

            # Audit success
            await self._audit_operation(
                action=AuditAction.READ,
                secret_name="*",
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "operation": "list",
                    "count": len(secrets),
                },
            )

            logger.info(
                "Secrets listed successfully",
                count=len(secrets),
                user_id=security_context.user_id,
            )

            return secrets

        except (AuthorizationError, AzureKeyVaultError):
            raise
        except _AZURE_OPERATION_ERRORS as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.READ,
                secret_name="*",
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"operation": "list", "error": str(e)},
            )
            self._handle_azure_error(e, "*", "list")
            raise

    async def purge_deleted_secret(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Permanently delete a soft-deleted secret.

        This operation is irreversible. The secret cannot be recovered
        after purging.

        Args:
            name: Name of the deleted secret to purge
            security_context: Security context with secrets.delete permission

        Returns:
            True if the operation succeeded

        Raises:
            AuthorizationError: If user lacks secrets.delete permission
            AzureSecretNotFoundError: If secret is not in deleted state
            AzureKeyVaultConnectionError: If unable to connect to Azure
            AzureKeyVaultError: For other Azure errors

        Example:
            ```python
            # First soft-delete the secret
            await client.delete_secret("myapp-old-config", context)

            # Then permanently purge it
            await client.purge_deleted_secret(
                name="myapp-old-config",
                security_context=context,
            )
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_DELETE, name)

        logger.debug(
            "Purging deleted secret from Azure Key Vault",
            secret_name=name,
            user_id=security_context.user_id,
        )

        try:
            client = await self._ensure_client()

            # Purge the deleted secret
            await client.purge_deleted_secret(name)

            # Audit success
            await self._audit_operation(
                action=AuditAction.PURGE,
                secret_name=name,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
            )

            logger.info(
                "Deleted secret purged successfully",
                secret_name=name,
                user_id=security_context.user_id,
            )

            return True

        except (AuthorizationError, AzureKeyVaultError):
            raise
        except _AZURE_OPERATION_ERRORS as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.PURGE,
                secret_name=name,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"error": str(e)},
            )
            self._handle_azure_error(e, name, "purge")
            raise

    async def recover_deleted_secret(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> Dict[str, Any]:
        """
        Recover a soft-deleted secret.

        Restores the secret to an active state. Only works for secrets
        that have been soft-deleted and not yet purged.

        Args:
            name: Name of the deleted secret to recover
            security_context: Security context with secrets.write permission

        Returns:
            Dictionary containing the recovered secret metadata

        Raises:
            AuthorizationError: If user lacks secrets.write permission
            AzureSecretNotFoundError: If secret is not in deleted state
            AzureKeyVaultConnectionError: If unable to connect to Azure
            AzureKeyVaultError: For other Azure errors

        Example:
            ```python
            # Recover a deleted secret
            result = await client.recover_deleted_secret(
                name="myapp-accidentally-deleted",
                security_context=context,
            )
            print(f"Recovered secret version: {result['version']}")
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_WRITE, name)

        logger.debug(
            "Recovering deleted secret from Azure Key Vault",
            secret_name=name,
            user_id=security_context.user_id,
        )

        try:
            client = await self._ensure_client()

            # Begin the recover operation
            poller = await client.begin_recover_deleted_secret(name)

            # Wait for completion and get the result
            secret = await poller.wait()

            # Build response dictionary
            result = {
                "name": secret.name,
                "version": secret.properties.version,
                "enabled": secret.properties.enabled,
                "created_on": secret.properties.created_on,
                "updated_on": secret.properties.updated_on,
                "expires_on": secret.properties.expires_on,
                "content_type": secret.properties.content_type,
                "tags": secret.properties.tags or {},
            }

            # Audit success
            await self._audit_operation(
                action=AuditAction.UPDATE,
                secret_name=name,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "operation": "recover",
                    "version": secret.properties.version,
                },
            )

            logger.info(
                "Deleted secret recovered successfully",
                secret_name=name,
                user_id=security_context.user_id,
            )

            return result

        except (AuthorizationError, AzureKeyVaultError):
            raise
        except _AZURE_OPERATION_ERRORS as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.UPDATE,
                secret_name=name,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"operation": "recover", "error": str(e)},
            )
            self._handle_azure_error(e, name, "recover")
            raise

    async def backup_secret(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> bytes:
        """
        Backup a secret.

        Creates a backup of the secret that can be restored to the same
        or a different vault within the same subscription.

        Args:
            name: Name of the secret to backup
            security_context: Security context with secrets.read permission

        Returns:
            Backup blob as bytes

        Raises:
            AuthorizationError: If user lacks secrets.read permission
            AzureSecretNotFoundError: If secret doesn't exist
            AzureKeyVaultConnectionError: If unable to connect to Azure
            AzureKeyVaultError: For other Azure errors

        Example:
            ```python
            # Backup a secret
            backup_data = await client.backup_secret(
                name="myapp-critical-secret",
                security_context=context,
            )

            # Store backup securely
            with open("secret_backup.bin", "wb") as f:
                f.write(backup_data)
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_READ, name)

        logger.debug(
            "Backing up secret from Azure Key Vault",
            secret_name=name,
            user_id=security_context.user_id,
        )

        try:
            client = await self._ensure_client()

            # Backup the secret
            backup_blob = await client.backup_secret(name)

            # Audit success
            await self._audit_operation(
                action=AuditAction.EXPORT,
                secret_name=name,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "operation": "backup",
                    "backup_size": len(backup_blob),
                },
            )

            logger.info(
                "Secret backed up successfully",
                secret_name=name,
                backup_size=len(backup_blob),
                user_id=security_context.user_id,
            )

            return backup_blob

        except (AuthorizationError, AzureKeyVaultError):
            raise
        except _AZURE_OPERATION_ERRORS as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.EXPORT,
                secret_name=name,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"operation": "backup", "error": str(e)},
            )
            self._handle_azure_error(e, name, "backup")
            raise

    async def restore_secret(
        self,
        backup: bytes,
        security_context: SecurityContext,
    ) -> Dict[str, Any]:
        """
        Restore a secret from backup.

        Restores a backed-up secret to the vault. The backup must have
        been created from a vault in the same subscription.

        Args:
            backup: Backup blob from backup_secret
            security_context: Security context with secrets.write permission

        Returns:
            Dictionary containing the restored secret metadata

        Raises:
            AuthorizationError: If user lacks secrets.write permission
            ValidationError: If backup is invalid
            AzureKeyVaultConnectionError: If unable to connect to Azure
            AzureKeyVaultError: For other Azure errors

        Example:
            ```python
            # Read backup from file
            with open("secret_backup.bin", "rb") as f:
                backup_data = f.read()

            # Restore the secret
            result = await client.restore_secret(
                backup=backup_data,
                security_context=context,
            )
            print(f"Restored secret: {result['name']}")
            ```
        """
        # Validate input
        if not backup:
            raise ValidationError(
                message="Backup data cannot be empty",
                suggestions=["Provide valid backup data from backup_secret"],
            )

        # Check permission
        self._check_permission(security_context, self.PERMISSION_WRITE, "*")

        logger.debug(
            "Restoring secret to Azure Key Vault",
            backup_size=len(backup),
            user_id=security_context.user_id,
        )

        try:
            client = await self._ensure_client()

            # Restore the secret
            secret = await client.restore_secret_backup(backup)

            # Build response dictionary
            result = {
                "name": secret.name,
                "version": secret.properties.version,
                "enabled": secret.properties.enabled,
                "created_on": secret.properties.created_on,
                "updated_on": secret.properties.updated_on,
                "expires_on": secret.properties.expires_on,
                "content_type": secret.properties.content_type,
                "tags": secret.properties.tags or {},
            }

            # Audit success
            await self._audit_operation(
                action=AuditAction.IMPORT,
                secret_name=secret.name,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "operation": "restore",
                    "version": secret.properties.version,
                },
            )

            logger.info(
                "Secret restored successfully",
                secret_name=secret.name,
                version=secret.properties.version,
                user_id=security_context.user_id,
            )

            return result

        except (AuthorizationError, ValidationError, AzureKeyVaultError):
            raise
        except _AZURE_OPERATION_ERRORS as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.IMPORT,
                secret_name="*",
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"operation": "restore", "error": str(e)},
            )
            self._handle_azure_error(e, "*", "restore")
            raise

    async def get_deleted_secret(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> Dict[str, Any]:
        """
        Get a deleted secret.

        Retrieves information about a soft-deleted secret that has not
        yet been purged.

        Args:
            name: Name of the deleted secret
            security_context: Security context with secrets.read permission

        Returns:
            Dictionary containing the deleted secret metadata with keys:
            - name: Secret name
            - version: Secret version
            - scheduled_purge_date: When the secret will be permanently deleted
            - deleted_on: When the secret was deleted
            - recovery_id: Recovery identifier
            - value: Secret value (if available)

        Raises:
            AuthorizationError: If user lacks secrets.read permission
            AzureSecretNotFoundError: If secret is not in deleted state
            AzureKeyVaultConnectionError: If unable to connect to Azure
            AzureKeyVaultError: For other Azure errors

        Example:
            ```python
            # Get information about a deleted secret
            deleted_secret = await client.get_deleted_secret(
                name="myapp-deleted-config",
                security_context=context,
            )
            print(f"Deleted on: {deleted_secret['deleted_on']}")
            print(f"Will be purged on: {deleted_secret['scheduled_purge_date']}")
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_READ, name)

        logger.debug(
            "Getting deleted secret from Azure Key Vault",
            secret_name=name,
            user_id=security_context.user_id,
        )

        try:
            client = await self._ensure_client()

            # Get the deleted secret
            deleted_secret = await client.get_deleted_secret(name)

            # Build response dictionary
            result = {
                "name": deleted_secret.name,
                "version": deleted_secret.properties.version,
                "value": deleted_secret.value,
                "scheduled_purge_date": deleted_secret.scheduled_purge_date,
                "deleted_on": deleted_secret.deleted_date,
                "recovery_id": deleted_secret.recovery_id,
                "content_type": deleted_secret.properties.content_type,
                "tags": deleted_secret.properties.tags or {},
            }

            # Audit success
            await self._audit_operation(
                action=AuditAction.READ,
                secret_name=name,
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "operation": "get_deleted",
                },
            )

            logger.info(
                "Deleted secret retrieved successfully",
                secret_name=name,
                user_id=security_context.user_id,
            )

            return result

        except (AuthorizationError, AzureKeyVaultError):
            raise
        except _AZURE_OPERATION_ERRORS as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.READ,
                secret_name=name,
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"operation": "get_deleted", "error": str(e)},
            )
            self._handle_azure_error(e, name, "get_deleted")
            raise

    async def list_deleted_secrets(
        self,
        security_context: SecurityContext,
        *,
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        List deleted secrets in Azure Key Vault.

        Retrieves a list of deleted secrets that have not yet been purged.

        Args:
            security_context: Security context with secrets.list permission
            max_results: Maximum number of secrets to return (None for all)

        Returns:
            List of deleted secret metadata dictionaries

        Raises:
            AuthorizationError: If user lacks secrets.list permission
            AzureKeyVaultConnectionError: If unable to connect to Azure
            AzureKeyVaultError: For other Azure errors

        Example:
            ```python
            # List all deleted secrets
            deleted_secrets = await client.list_deleted_secrets(
                security_context=context,
            )
            for secret in deleted_secrets:
                print(f"Name: {secret['name']}, Deleted on: {secret['deleted_on']}")
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_LIST, "*")

        logger.debug(
            "Listing deleted secrets in Azure Key Vault",
            max_results=max_results,
            user_id=security_context.user_id,
        )

        try:
            client = await self._ensure_client()

            secrets: List[Dict[str, Any]] = []

            # List deleted secrets
            async for deleted_secret in client.list_deleted_secrets():
                secrets.append({
                    "name": deleted_secret.name,
                    "version": deleted_secret.properties.version,
                    "deleted_on": deleted_secret.deleted_date,
                    "scheduled_purge_date": deleted_secret.scheduled_purge_date,
                    "recovery_id": deleted_secret.recovery_id,
                    "tags": deleted_secret.properties.tags or {},
                })

                if max_results and len(secrets) >= max_results:
                    break

            # Audit success
            await self._audit_operation(
                action=AuditAction.READ,
                secret_name="*",
                status=AuditStatus.SUCCESS,
                security_context=security_context,
                metadata={
                    "operation": "list_deleted",
                    "count": len(secrets),
                },
            )

            logger.info(
                "Deleted secrets listed successfully",
                count=len(secrets),
                user_id=security_context.user_id,
            )

            return secrets

        except (AuthorizationError, AzureKeyVaultError):
            raise
        except _AZURE_OPERATION_ERRORS as e:
            # Audit failure
            await self._audit_operation(
                action=AuditAction.READ,
                secret_name="*",
                status=AuditStatus.FAILURE,
                security_context=security_context,
                metadata={"operation": "list_deleted", "error": str(e)},
            )
            self._handle_azure_error(e, "*", "list_deleted")
            raise

    async def close(self) -> None:
        """
        Close the Azure Key Vault client and clean up resources.

        Should be called when done using the client to properly
        close connections.

        Example:
            ```python
            client = AzureKeyVaultClient(config)
            try:
                secret = await client.get_secret("myapp-config", context)
            finally:
                await client.close()

            # Or use as async context manager (recommended)
            async with AzureKeyVaultClient(config) as client:
                secret = await client.get_secret("myapp-config", context)
            ```
        """
        if self._client:
            try:
                await self._client.close()
            except (ConnectionError, TimeoutError, OSError, AgenticBaseException) as e:
                logger.warning("Error closing Azure Key Vault client", exc_info=e)
            self._client = None

        if self._credential and hasattr(self._credential, "close"):
            try:
                await self._credential.close()
            except (ConnectionError, TimeoutError, OSError, AgenticBaseException) as e:
                logger.warning("Error closing Azure credential", exc_info=e)
            self._credential = None

        logger.debug("Azure Key Vault client session closed")

    async def __aenter__(self) -> "AzureKeyVaultClient":
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
        Check if Azure Key Vault is healthy and accessible.

        Performs a simple list operation to verify connectivity
        and credentials.

        Returns:
            True if Azure Key Vault is accessible, False otherwise

        Example:
            ```python
            is_healthy = await client.health_check()
            if not is_healthy:
                logger.warning("Azure Key Vault is not accessible")
            ```
        """
        try:
            client = await self._ensure_client()
            # Perform a simple list with small limit to check connectivity
            async for _ in client.list_properties_of_secrets():
                break  # Just need to check connectivity
            return True
        except (ConnectionError, TimeoutError, OSError, AgenticBaseException) as e:
            logger.warning("Azure Key Vault health check failed", exc_info=e)
            return False
