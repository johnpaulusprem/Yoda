"""
Credentials management for the Agentic AI Component Library Data Access layer.

This module provides secure credential handling for database and service
connections, including encryption, validation, and secure storage.

Example:
    ```python
    from yoda_foundation.data_access.base import (
        Credentials,
        CredentialType,
        CredentialStore,
    )
    from yoda_foundation.security import create_security_context

    # Create credentials
    db_creds = Credentials(
        credential_type=CredentialType.PASSWORD,
        username="db_user",
        password="secure_password",
    )

    # Store credentials securely
    context = create_security_context(
        user_id="admin",
        permissions=["credentials.write"],
    )
    store = CredentialStore()
    await store.store_credentials("postgres_prod", db_creds, context)

    # Retrieve credentials
    creds = await store.get_credentials("postgres_prod", context)
    ```
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from yoda_foundation.exceptions import (
    AuthorizationError,
)
from yoda_foundation.exceptions.base import (
    AgenticBaseException,
    ErrorCategory,
    ErrorSeverity,
)
from yoda_foundation.security.context import SecurityContext


class CredentialType(Enum):
    """
    Types of credentials supported for authentication.

    Attributes:
        PASSWORD: Username/password combination
        API_KEY: API key authentication
        OAUTH: OAuth 2.0 token-based authentication
        CERTIFICATE: Certificate-based authentication
        AWS_IAM: AWS IAM role-based authentication
        SERVICE_ACCOUNT: Service account credentials (e.g., GCP)
        CONNECTION_STRING: Full connection string
    """

    PASSWORD = "password"
    API_KEY = "api_key"
    OAUTH = "oauth"
    CERTIFICATE = "certificate"
    AWS_IAM = "aws_iam"
    SERVICE_ACCOUNT = "service_account"
    CONNECTION_STRING = "connection_string"


class CredentialError(AgenticBaseException):
    """
    Base exception for credential-related errors.

    Attributes:
        credential_name: Name of the credential
        operation: Operation that failed

    Example:
        ```python
        raise CredentialError(
            message="Failed to retrieve credential",
            credential_name="postgres_prod",
            operation="get",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Credential operation failed",
        *,
        credential_name: str | None = None,
        operation: str | None = None,
        suggestions: list[str] | None = None,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize credential error.

        Args:
            message: Human-readable error description
            credential_name: Name of the credential
            operation: Operation that failed (get, store, delete, validate)
            suggestions: Actionable remediation steps
            cause: Original exception
            details: Additional context
        """
        self.credential_name = credential_name
        self.operation = operation

        extra_details = {
            "credential_name": credential_name,
            "operation": operation,
        }

        merged_details = {**extra_details, **(details or {})}

        super().__init__(
            message=message,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.HIGH,
            retryable=False,
            user_message="Credential operation failed. Please check your configuration.",
            suggestions=suggestions
            or [
                "Verify credential name is correct",
                "Check access permissions",
                "Ensure credential exists",
            ],
            cause=cause,
            details=merged_details,
        )


class CredentialNotFoundError(CredentialError):
    """
    Credential not found in store.

    Example:
        ```python
        raise CredentialNotFoundError(credential_name="postgres_prod")
        ```
    """

    def __init__(
        self,
        credential_name: str,
        *,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize credential not found error."""
        super().__init__(
            message=f"Credential not found: '{credential_name}'",
            credential_name=credential_name,
            operation="get",
            suggestions=[
                f"Verify credential '{credential_name}' exists",
                "Check for typos in credential name",
                "Store the credential before attempting to retrieve it",
            ],
            cause=cause,
            details=details,
        )
        self.user_message = "The requested credential was not found."


class CredentialValidationError(CredentialError):
    """
    Credential validation failed.

    Example:
        ```python
        raise CredentialValidationError(
            credential_name="postgres_prod",
            validation_errors=["password is required"],
        )
        ```
    """

    def __init__(
        self,
        credential_name: str | None = None,
        validation_errors: list[str] | None = None,
        *,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize credential validation error."""
        errors = validation_errors or ["Unknown validation error"]
        error_str = "; ".join(errors)

        extra_details = {"validation_errors": validation_errors}
        merged_details = {**extra_details, **(details or {})}

        super().__init__(
            message=f"Credential validation failed: {error_str}",
            credential_name=credential_name,
            operation="validate",
            suggestions=[
                "Check all required fields are provided",
                "Verify credential format matches type",
                "Ensure sensitive values are not empty",
            ],
            cause=cause,
            details=merged_details,
        )
        self.validation_errors = validation_errors or []
        self.user_message = "The provided credentials are invalid."


class CredentialEncryptionError(CredentialError):
    """
    Credential encryption/decryption failed.

    Example:
        ```python
        raise CredentialEncryptionError(
            message="Failed to decrypt credential",
            credential_name="api_key_prod",
            operation="decrypt",
        )
        ```
    """

    def __init__(
        self,
        message: str = "Encryption operation failed",
        *,
        credential_name: str | None = None,
        operation: str = "encrypt",
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize credential encryption error."""
        super().__init__(
            message=message,
            credential_name=credential_name,
            operation=operation,
            suggestions=[
                "Verify encryption key is valid",
                "Check key has not been rotated",
                "Ensure credential was encrypted with current key",
            ],
            cause=cause,
            details=details,
        )
        self.user_message = "Failed to process credential encryption."


@dataclass
class Credentials:
    """
    Container for authentication credentials.

    Holds various types of credentials for database and service
    authentication with secure handling.

    Attributes:
        credential_type: Type of credential (PASSWORD, API_KEY, etc.)
        username: Username for password-based auth
        password: Password for password-based auth
        api_key: API key for key-based auth
        token: OAuth or other token
        certificate_path: Path to certificate file
        private_key_path: Path to private key file
        extra: Additional credential data
        created_at: When credential was created
        expires_at: When credential expires (optional)
        metadata: Non-sensitive metadata

    Example:
        ```python
        # Password credentials
        db_creds = Credentials(
            credential_type=CredentialType.PASSWORD,
            username="db_user",
            password="secure_password",
        )

        # API key credentials
        api_creds = Credentials(
            credential_type=CredentialType.API_KEY,
            api_key="sk-xxxxx",
        )

        # OAuth token
        oauth_creds = Credentials(
            credential_type=CredentialType.OAUTH,
            token="eyJ...",
            extra={"refresh_token": "..."},
        )

        # Certificate-based
        cert_creds = Credentials(
            credential_type=CredentialType.CERTIFICATE,
            certificate_path="/path/to/cert.pem",
            private_key_path="/path/to/key.pem",
        )
        ```

    Raises:
        CredentialValidationError: If validation fails
    """

    credential_type: CredentialType
    username: str | None = None
    password: str | None = None
    api_key: str | None = None
    token: str | None = None
    certificate_path: str | None = None
    private_key_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate credentials after initialization."""
        # Convert string to enum if needed
        if isinstance(self.credential_type, str):
            self.credential_type = CredentialType(self.credential_type)

    @property
    def is_expired(self) -> bool:
        """
        Check if credential has expired.

        Returns:
            True if credential is past expiration date
        """
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def validate(self) -> list[str]:
        """
        Validate credential completeness based on type.

        Returns:
            List of validation error messages (empty if valid)

        Example:
            ```python
            errors = creds.validate()
            if errors:
                raise CredentialValidationError(
                    validation_errors=errors
                )
            ```
        """
        errors: list[str] = []

        if self.credential_type == CredentialType.PASSWORD:
            if not self.username:
                errors.append("username is required for PASSWORD credentials")
            if not self.password:
                errors.append("password is required for PASSWORD credentials")

        elif self.credential_type == CredentialType.API_KEY:
            if not self.api_key:
                errors.append("api_key is required for API_KEY credentials")

        elif self.credential_type == CredentialType.OAUTH:
            if not self.token:
                errors.append("token is required for OAUTH credentials")

        elif self.credential_type == CredentialType.CERTIFICATE:
            if not self.certificate_path:
                errors.append("certificate_path is required for CERTIFICATE credentials")

        elif self.credential_type == CredentialType.CONNECTION_STRING:
            if "connection_string" not in self.extra:
                errors.append(
                    "connection_string in extra is required for CONNECTION_STRING credentials"
                )

        if self.is_expired:
            errors.append("credential has expired")

        return errors

    def to_dict(self, include_sensitive: bool = False) -> dict[str, Any]:
        """
        Convert credentials to dictionary.

        Args:
            include_sensitive: Whether to include sensitive values

        Returns:
            Dictionary representation

        Example:
            ```python
            # For logging (no sensitive data)
            log_data = creds.to_dict(include_sensitive=False)

            # For storage (with sensitive data)
            store_data = creds.to_dict(include_sensitive=True)
            ```
        """
        result: dict[str, Any] = {
            "credential_type": self.credential_type.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata,
        }

        if include_sensitive:
            result.update(
                {
                    "username": self.username,
                    "password": self.password,
                    "api_key": self.api_key,
                    "token": self.token,
                    "certificate_path": self.certificate_path,
                    "private_key_path": self.private_key_path,
                    "extra": self.extra,
                }
            )
        else:
            # Include non-sensitive identifiers
            result["username"] = self.username
            result["certificate_path"] = self.certificate_path
            result["has_password"] = self.password is not None
            result["has_api_key"] = self.api_key is not None
            result["has_token"] = self.token is not None

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Credentials:
        """
        Create credentials from dictionary.

        Args:
            data: Dictionary with credential data

        Returns:
            Credentials instance

        Example:
            ```python
            creds = Credentials.from_dict({
                "credential_type": "password",
                "username": "user",
                "password": "pass",
            })
            ```
        """
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        expires_at = data.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)

        return cls(
            credential_type=CredentialType(data["credential_type"]),
            username=data.get("username"),
            password=data.get("password"),
            api_key=data.get("api_key"),
            token=data.get("token"),
            certificate_path=data.get("certificate_path"),
            private_key_path=data.get("private_key_path"),
            extra=data.get("extra", {}),
            created_at=created_at or datetime.now(UTC),
            expires_at=expires_at,
            metadata=data.get("metadata", {}),
        )

    def mask_sensitive(self) -> Credentials:
        """
        Create a copy with sensitive values masked.

        Returns:
            New Credentials instance with masked values

        Example:
            ```python
            masked = creds.mask_sensitive()
            logger.info(f"Using credentials: {masked}")
            ```
        """
        return Credentials(
            credential_type=self.credential_type,
            username=self.username,
            password="****" if self.password else None,
            api_key="****" if self.api_key else None,
            token="****" if self.token else None,
            certificate_path=self.certificate_path,
            private_key_path=self.private_key_path,
            extra={
                k: "****"
                if "secret" in k.lower() or "key" in k.lower() or "password" in k.lower()
                else v
                for k, v in self.extra.items()
            },
            created_at=self.created_at,
            expires_at=self.expires_at,
            metadata=self.metadata,
        )

    def __repr__(self) -> str:
        """Return string representation with masked sensitive values."""
        masked = self.mask_sensitive()
        return (
            f"Credentials(type={masked.credential_type.value}, "
            f"username={masked.username}, "
            f"has_password={self.password is not None}, "
            f"has_api_key={self.api_key is not None})"
        )


class EncryptionProvider(Protocol):
    """
    Protocol for credential encryption providers.

    Implementations provide encryption and decryption of sensitive
    credential values.
    """

    async def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext value.

        Args:
            plaintext: The plaintext string to encrypt.

        Returns:
            The encrypted ciphertext string.
        """
        ...

    async def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt an encrypted value.

        Args:
            ciphertext: The encrypted string to decrypt.

        Returns:
            The decrypted plaintext string.
        """
        ...


class SimpleEncryptionProvider:
    """
    Simple encryption provider using Fernet-like encryption.

    Uses PBKDF2 key derivation and AES encryption for credential
    protection. Suitable for development and testing.

    WARNING: For production use, prefer a proper secrets manager
    like HashiCorp Vault or AWS Secrets Manager.

    Attributes:
        _key: Encryption key derived from password

    Example:
        ```python
        provider = SimpleEncryptionProvider(
            password="your-secure-password",
            salt="your-salt-value",
        )

        encrypted = await provider.encrypt("secret-value")
        decrypted = await provider.decrypt(encrypted)
        ```
    """

    def __init__(
        self,
        password: str | None = None,
        salt: str | None = None,
    ) -> None:
        """
        Initialize encryption provider.

        Args:
            password: Encryption password (uses env var if not provided)
            salt: Salt for key derivation (uses env var if not provided)
        """
        self._password = password or os.environ.get("AGENTIC_CREDENTIAL_KEY", secrets.token_hex(32))
        salt_value = salt or os.environ.get("AGENTIC_CREDENTIAL_SALT")
        if not salt_value:
            salt_value = secrets.token_hex(16)
        self._salt = salt_value.encode()

        # Derive key using PBKDF2
        self._key = hashlib.pbkdf2_hmac(
            "sha256",
            self._password.encode(),
            self._salt,
            100000,
            dklen=32,
        )

    async def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext value.

        Args:
            plaintext: Value to encrypt

        Returns:
            Base64-encoded encrypted value

        Raises:
            CredentialEncryptionError: If encryption fails
        """
        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._encrypt_sync, plaintext)
        except (OSError, ValueError, RuntimeError) as e:
            raise CredentialEncryptionError(
                message=f"Encryption failed: {e}",
                operation="encrypt",
                cause=e,
            )

    def _encrypt_sync(self, plaintext: str) -> str:
        """Synchronous encryption implementation using Fernet.

        Args:
            plaintext: The plaintext string to encrypt.

        Returns:
            Base64-encoded encrypted string.

        Raises:
            CredentialEncryptionError: If cryptography library is not installed.
        """
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            raise CredentialEncryptionError(
                message="The 'cryptography' package is required for credential encryption. "
                "Install it with: pip install cryptography",
                operation="encrypt",
            )

        fernet_key = base64.urlsafe_b64encode(self._key)
        fernet = Fernet(fernet_key)

        encrypted = fernet.encrypt(plaintext.encode())
        return encrypted.decode()

    async def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt an encrypted value.

        Args:
            ciphertext: Encrypted value to decrypt

        Returns:
            Decrypted plaintext

        Raises:
            CredentialEncryptionError: If decryption fails
        """
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._decrypt_sync, ciphertext)
        except CredentialEncryptionError:
            raise
        except (OSError, ValueError, RuntimeError) as e:
            raise CredentialEncryptionError(
                message=f"Decryption failed: {e}",
                operation="decrypt",
                cause=e,
            )

    def _decrypt_sync(self, ciphertext: str) -> str:
        """Synchronous decryption implementation using Fernet.

        Args:
            ciphertext: The encrypted string to decrypt.

        Returns:
            The decrypted plaintext string.

        Raises:
            CredentialEncryptionError: If cryptography library is not installed
                or decryption fails.
        """
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            raise CredentialEncryptionError(
                message="The 'cryptography' package is required for credential decryption. "
                "Install it with: pip install cryptography",
                operation="decrypt",
            )

        fernet_key = base64.urlsafe_b64encode(self._key)
        fernet = Fernet(fernet_key)

        decrypted = fernet.decrypt(ciphertext.encode())
        return decrypted.decode()


class CredentialStore(ABC):
    """
    Abstract base class for credential storage.

    Provides secure storage and retrieval of credentials with
    encryption and access control.

    Subclasses should implement the abstract methods for specific
    storage backends (in-memory, file, database, vault, etc.).

    Example:
        ```python
        class MyCredentialStore(CredentialStore):
            async def _store(self, name: str, data: Dict[str, Any]) -> bool:
                # Store in your backend
                pass

            async def _retrieve(self, name: str) -> Optional[Dict[str, Any]]:
                # Retrieve from your backend
                pass

            async def _delete(self, name: str) -> bool:
                # Delete from your backend
                pass

            async def _exists(self, name: str) -> bool:
                # Check if exists in your backend
                pass
        ```
    """

    # Permission constants
    PERMISSION_READ = "credentials.read"
    PERMISSION_WRITE = "credentials.write"
    PERMISSION_DELETE = "credentials.delete"

    def __init__(
        self,
        encryption_provider: EncryptionProvider | None = None,
    ) -> None:
        """
        Initialize credential store.

        Args:
            encryption_provider: Provider for encrypting credentials
        """
        self._encryption = encryption_provider or SimpleEncryptionProvider()

    def _check_permission(
        self,
        security_context: SecurityContext,
        permission: str,
        credential_name: str,
    ) -> None:
        """
        Check if security context has required permission.

        Args:
            security_context: Security context to check
            permission: Required permission
            credential_name: Credential being accessed

        Raises:
            AuthorizationError: If permission not granted
        """
        if not security_context.has_permission(permission):
            raise AuthorizationError(
                message=f"Permission denied: {permission}",
                required_permission=permission,
                resource=f"credential:{credential_name}",
                user_id=security_context.user_id,
            )

    async def get_credentials(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> Credentials:
        """
        Retrieve credentials by name.

        Args:
            name: Credential name/identifier
            security_context: Security context with credentials.read permission

        Returns:
            Credentials object

        Raises:
            AuthorizationError: If user lacks credentials.read permission
            CredentialNotFoundError: If credential doesn't exist
            CredentialEncryptionError: If decryption fails

        Example:
            ```python
            creds = await store.get_credentials(
                "postgres_prod",
                security_context,
            )
            conn = await connect(
                host="db.example.com",
                user=creds.username,
                password=creds.password,
            )
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_READ, name)

        # Retrieve from storage
        data = await self._retrieve(name)
        if data is None:
            raise CredentialNotFoundError(credential_name=name)

        # Decrypt sensitive fields
        decrypted_data = await self._decrypt_credential_data(data)

        return Credentials.from_dict(decrypted_data)

    async def store_credentials(
        self,
        name: str,
        credentials: Credentials,
        security_context: SecurityContext,
    ) -> bool:
        """
        Store credentials securely.

        Args:
            name: Credential name/identifier
            credentials: Credentials to store
            security_context: Security context with credentials.write permission

        Returns:
            True if stored successfully

        Raises:
            AuthorizationError: If user lacks credentials.write permission
            CredentialValidationError: If credentials are invalid
            CredentialEncryptionError: If encryption fails

        Example:
            ```python
            creds = Credentials(
                credential_type=CredentialType.PASSWORD,
                username="db_user",
                password="secure_password",
            )

            success = await store.store_credentials(
                "postgres_prod",
                creds,
                security_context,
            )
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_WRITE, name)

        # Validate credentials
        errors = credentials.validate()
        if errors:
            raise CredentialValidationError(
                credential_name=name,
                validation_errors=errors,
            )

        # Convert to dict and encrypt sensitive fields
        data = credentials.to_dict(include_sensitive=True)
        encrypted_data = await self._encrypt_credential_data(data)

        # Add storage metadata
        encrypted_data["_stored_at"] = datetime.now(UTC).isoformat()
        encrypted_data["_stored_by"] = security_context.user_id

        # Store
        return await self._store(name, encrypted_data)

    async def delete_credentials(
        self,
        name: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Delete credentials from store.

        Args:
            name: Credential name/identifier
            security_context: Security context with credentials.delete permission

        Returns:
            True if deleted successfully

        Raises:
            AuthorizationError: If user lacks credentials.delete permission
            CredentialNotFoundError: If credential doesn't exist

        Example:
            ```python
            success = await store.delete_credentials(
                "old_api_key",
                security_context,
            )
            ```
        """
        # Check permission
        self._check_permission(security_context, self.PERMISSION_DELETE, name)

        # Check exists
        if not await self._exists(name):
            raise CredentialNotFoundError(credential_name=name)

        return await self._delete(name)

    async def validate(self, credentials: Credentials) -> bool:
        """
        Validate credential completeness and format.

        Args:
            credentials: Credentials to validate

        Returns:
            True if valid

        Raises:
            CredentialValidationError: If validation fails

        Example:
            ```python
            creds = Credentials(
                credential_type=CredentialType.PASSWORD,
                username="user",
                # Missing password
            )

            try:
                await store.validate(creds)
            except CredentialValidationError as e:
                print(e.validation_errors)
            ```
        """
        errors = credentials.validate()
        if errors:
            raise CredentialValidationError(validation_errors=errors)
        return True

    async def encrypt(self, value: str) -> str:
        """
        Encrypt a sensitive value.

        Args:
            value: Plaintext value to encrypt

        Returns:
            Encrypted value

        Raises:
            CredentialEncryptionError: If encryption fails

        Example:
            ```python
            encrypted_password = await store.encrypt("my_password")
            ```
        """
        return await self._encryption.encrypt(value)

    async def decrypt(self, value: str) -> str:
        """
        Decrypt an encrypted value.

        Args:
            value: Encrypted value to decrypt

        Returns:
            Decrypted plaintext

        Raises:
            CredentialEncryptionError: If decryption fails

        Example:
            ```python
            password = await store.decrypt(encrypted_password)
            ```
        """
        return await self._encryption.decrypt(value)

    async def _encrypt_credential_data(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Encrypt sensitive fields in credential data.

        Args:
            data: Credential data dictionary

        Returns:
            Dictionary with encrypted sensitive fields
        """
        sensitive_fields = ["password", "api_key", "token"]
        encrypted = data.copy()

        for field_name in sensitive_fields:
            if encrypted.get(field_name):
                encrypted[field_name] = await self._encryption.encrypt(encrypted[field_name])
                encrypted[f"_{field_name}_encrypted"] = True

        # Handle extra dict
        if encrypted.get("extra"):
            encrypted_extra = encrypted["extra"].copy()
            for key, value in encrypted["extra"].items():
                if isinstance(value, str) and any(
                    s in key.lower() for s in ["secret", "key", "password", "token"]
                ):
                    encrypted_extra[key] = await self._encryption.encrypt(value)
                    encrypted_extra[f"_{key}_encrypted"] = True
            encrypted["extra"] = encrypted_extra

        return encrypted

    async def _decrypt_credential_data(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Decrypt sensitive fields in credential data.

        Args:
            data: Encrypted credential data

        Returns:
            Dictionary with decrypted sensitive fields
        """
        sensitive_fields = ["password", "api_key", "token"]
        decrypted = data.copy()

        for field_name in sensitive_fields:
            if decrypted.get(f"_{field_name}_encrypted") and decrypted.get(field_name):
                decrypted[field_name] = await self._encryption.decrypt(decrypted[field_name])
                del decrypted[f"_{field_name}_encrypted"]

        # Handle extra dict
        if decrypted.get("extra"):
            decrypted_extra = decrypted["extra"].copy()
            for key in list(decrypted_extra.keys()):
                if key.startswith("_") and key.endswith("_encrypted"):
                    continue
                encrypted_marker = f"_{key}_encrypted"
                if decrypted_extra.get(encrypted_marker):
                    decrypted_extra[key] = await self._encryption.decrypt(decrypted_extra[key])
                    del decrypted_extra[encrypted_marker]
            decrypted["extra"] = decrypted_extra

        return decrypted

    @abstractmethod
    async def _store(self, name: str, data: dict[str, Any]) -> bool:
        """
        Store credential data in backend.

        Args:
            name: Credential name
            data: Encrypted credential data

        Returns:
            True if stored successfully
        """
        pass

    @abstractmethod
    async def _retrieve(self, name: str) -> dict[str, Any] | None:
        """
        Retrieve credential data from backend.

        Args:
            name: Credential name

        Returns:
            Encrypted credential data or None if not found
        """
        pass

    @abstractmethod
    async def _delete(self, name: str) -> bool:
        """
        Delete credential from backend.

        Args:
            name: Credential name

        Returns:
            True if deleted successfully
        """
        pass

    @abstractmethod
    async def _exists(self, name: str) -> bool:
        """
        Check if credential exists in backend.

        Args:
            name: Credential name

        Returns:
            True if credential exists
        """
        pass


class InMemoryCredentialStore(CredentialStore):
    """
    In-memory credential store for development and testing.

    WARNING: Credentials are stored in memory and will be lost
    when the process ends. Use only for development/testing.

    Example:
        ```python
        store = InMemoryCredentialStore()

        # Store credential
        creds = Credentials(
            credential_type=CredentialType.PASSWORD,
            username="user",
            password="pass",
        )
        await store.store_credentials("test_db", creds, context)

        # Retrieve credential
        retrieved = await store.get_credentials("test_db", context)
        ```
    """

    def __init__(
        self,
        encryption_provider: EncryptionProvider | None = None,
    ) -> None:
        """Initialize in-memory credential store."""
        super().__init__(encryption_provider)
        self._store_data: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def _store(self, name: str, data: dict[str, Any]) -> bool:
        """
        Store credential data in memory.

        Args:
            name: Unique credential identifier.
            data: Encrypted credential data dictionary.

        Returns:
            True if stored successfully.
        """
        async with self._lock:
            self._store_data[name] = data
            return True

    async def _retrieve(self, name: str) -> dict[str, Any] | None:
        """
        Retrieve credential data from memory.

        Args:
            name: Unique credential identifier.

        Returns:
            Encrypted credential data dictionary, or None if not found.
        """
        async with self._lock:
            return self._store_data.get(name)

    async def _delete(self, name: str) -> bool:
        """
        Delete credential from memory.

        Args:
            name: Unique credential identifier.

        Returns:
            True if deleted successfully, False if not found.
        """
        async with self._lock:
            if name in self._store_data:
                del self._store_data[name]
                return True
            return False

    async def _exists(self, name: str) -> bool:
        """
        Check if credential exists in memory.

        Args:
            name: Unique credential identifier.

        Returns:
            True if credential exists, False otherwise.
        """
        async with self._lock:
            return name in self._store_data

    async def list_credentials(
        self,
        security_context: SecurityContext,
    ) -> list[str]:
        """
        List all credential names.

        Args:
            security_context: Security context with credentials.read permission

        Returns:
            List of credential names

        Example:
            ```python
            names = await store.list_credentials(context)
            for name in names:
                print(f"Credential: {name}")
            ```
        """
        self._check_permission(security_context, self.PERMISSION_READ, "*")

        async with self._lock:
            return list(self._store_data.keys())

    async def clear(self, security_context: SecurityContext) -> int:
        """
        Clear all credentials from store.

        Args:
            security_context: Security context with credentials.delete permission

        Returns:
            Number of credentials removed

        Example:
            ```python
            # Clear all credentials (for testing cleanup)
            removed = await store.clear(admin_context)
            print(f"Removed {removed} credentials")
            ```
        """
        self._check_permission(security_context, self.PERMISSION_DELETE, "*")

        async with self._lock:
            count = len(self._store_data)
            self._store_data.clear()
            return count
