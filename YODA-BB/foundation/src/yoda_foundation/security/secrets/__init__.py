"""
Secrets management module for the Agentic AI Component Library.

This module provides secure secrets management capabilities including
integration with HashiCorp Vault, AWS Secrets Manager, and Azure Key Vault
for storing, retrieving, and rotating sensitive credentials.

Example (HashiCorp Vault):
    ```python
    from yoda_foundation.security.secrets import (
        VaultClient,
        VaultConfig,
        AuthMethod,
        SecretMetadata,
        SecretResult,
        # Exceptions
        SecretsError,
        VaultConnectionError,
        SecretNotFoundError,
        SecretAccessDeniedError,
    )
    from yoda_foundation.security import create_security_context

    # Configure the Vault client
    config = VaultConfig(
        url="https://vault.example.com:8200",
        token="hvs.your-token-here",
        namespace="my-namespace",
        timeout=30.0,
        verify_ssl=True,
    )

    # Create the client
    async with VaultClient(config) as client:
        # Create security context with appropriate permissions
        context = create_security_context(
            user_id="user_123",
            permissions=[
                "secrets.read",
                "secrets.write",
                "secrets.list",
                "secrets.delete",
            ],
        )

        # Get a secret
        try:
            secret = await client.get_secret(
                path="myapp/database",
                security_context=context,
            )
            db_password = secret["password"]
        except SecretNotFoundError:
            print("Secret not found")
        except SecretAccessDeniedError:
            print("Access denied")

        # Set a secret
        await client.set_secret(
            path="myapp/api",
            data={
                "api_key": "my-api-key",
                "api_secret": "my-api-secret",
            },
            security_context=context,
        )

        # List secrets
        secrets = await client.list_secrets(
            path="myapp/",
            security_context=context,
        )
        print(f"Found secrets: {secrets}")

        # Rotate a secret
        new_secret = await client.rotate_secret(
            path="myapp/api",
            security_context=context,
        )
        print(f"New API key: {new_secret['api_key']}")

        # Delete a secret
        await client.delete_secret(
            path="myapp/old-config",
            security_context=context,
        )
    ```

Example (AWS Secrets Manager):
    ```python
    from yoda_foundation.security.secrets import (
        AWSSecretsManager,
        AWSSecretsConfig,
        AWSSecretMetadata,
        # Exceptions
        AWSSecretsError,
        AWSSecretsConnectionError,
        AWSSecretNotFoundError,
        AWSSecretAccessDeniedError,
        AWSSecretRotationError,
    )
    from yoda_foundation.security import create_security_context

    # Configure the AWS Secrets Manager client
    config = AWSSecretsConfig(
        region_name="us-east-1",
        profile_name="production",  # Or use explicit credentials
    )

    # Create the client
    async with AWSSecretsManager(config) as client:
        # Create security context
        context = create_security_context(
            user_id="user_123",
            permissions=[
                "secrets.read",
                "secrets.write",
                "secrets.list",
                "secrets.delete",
            ],
        )

        # Get a secret
        try:
            secret = await client.get_secret(
                secret_id="myapp/database-credentials",
                security_context=context,
            )
            db_password = secret["password"]
        except AWSSecretNotFoundError:
            print("Secret not found")
        except AWSSecretAccessDeniedError:
            print("Access denied")

        # Create a secret
        arn = await client.create_secret(
            name="myapp/api-key",
            secret_value={"api_key": "my-secret-key"},
            security_context=context,
            description="API key for external service",
        )

        # List secrets with filter
        secrets = await client.list_secrets(
            security_context=context,
            filters=[{"Key": "name", "Values": ["myapp/"]}],
        )
        for secret in secrets:
            print(f"Name: {secret['name']}, ARN: {secret['arn']}")

        # Rotate a secret
        version_id = await client.rotate_secret(
            secret_id="myapp/database-credentials",
            security_context=context,
        )
    ```

Example (Azure Key Vault):
    ```python
    from yoda_foundation.security.secrets import (
        AzureKeyVaultClient,
        AzureKeyVaultConfig,
        AzureSecretMetadata,
        # Exceptions
        AzureKeyVaultError,
        AzureKeyVaultConnectionError,
        AzureSecretNotFoundError,
        AzureSecretAccessDeniedError,
        AzureSecretDeletedError,
    )
    from yoda_foundation.security import create_security_context

    # Configure the Azure Key Vault client
    config = AzureKeyVaultConfig(
        vault_url="https://my-vault.vault.azure.net/",
        tenant_id="your-tenant-id",
        client_id="your-client-id",
        client_secret="your-client-secret",
    )

    # Create the client
    async with AzureKeyVaultClient(config) as client:
        # Create security context
        context = create_security_context(
            user_id="user_123",
            permissions=[
                "secrets.read",
                "secrets.write",
                "secrets.list",
                "secrets.delete",
            ],
        )

        # Get a secret
        try:
            secret = await client.get_secret(
                name="myapp-database-password",
                security_context=context,
            )
            db_password = secret["value"]
        except AzureSecretNotFoundError:
            print("Secret not found")
        except AzureSecretAccessDeniedError:
            print("Access denied")

        # Set a secret
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
        await client.recover_deleted_secret(
            name="myapp-old-config",
            security_context=context,
        )

        # Permanently purge a deleted secret
        await client.purge_deleted_secret(
            name="myapp-old-config",
            security_context=context,
        )

        # Backup and restore
        backup_data = await client.backup_secret("myapp-critical", context)
        restored = await client.restore_secret(backup_data, context)
    ```

Permissions:
    The following permissions are used by all secrets clients:
    - `secrets.read`: Required for get_secret, list_secrets, get_secret_metadata, backup_secret
    - `secrets.write`: Required for set_secret/create_secret/update_secret, rotate_secret, recover_deleted_secret, restore_secret
    - `secrets.delete`: Required for delete_secret, purge_deleted_secret
    - `secrets.list`: Required for list_secrets, list_deleted_secrets

Authentication Methods (Vault):
    The VaultClient supports multiple authentication methods:
    - TOKEN: Direct token authentication (default)
    - APPROLE: AppRole authentication for applications
    - KUBERNETES: Kubernetes service account authentication
    - AWS_IAM: AWS IAM authentication
    - LDAP: LDAP authentication

Authentication Methods (AWS):
    The AWSSecretsManager supports AWS credential chain:
    - Explicit credentials (access_key_id, secret_access_key)
    - AWS profile (profile_name)
    - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    - IAM roles (EC2, ECS, Lambda)
    - Session tokens for temporary credentials

Authentication Methods (Azure):
    The AzureKeyVaultClient supports Azure credential chain:
    - Service principal (tenant_id, client_id, client_secret)
    - DefaultAzureCredential (managed identity, Azure CLI, etc.)
    - Custom credential object (ManagedIdentityCredential, etc.)

Security Considerations:
    - Always use SSL/TLS in production
    - Store tokens and credentials securely, never in source code
    - Use short-lived tokens/credentials when possible
    - Enable audit logging for compliance
    - Implement least-privilege access policies
    - Use KMS for encryption in AWS Secrets Manager
    - Enable soft-delete and purge protection in Azure Key Vault
"""

from yoda_foundation.security.secrets.vault_client import (
    # Main client
    VaultClient,
    # Configuration
    VaultConfig,
    AuthMethod,
    # Data classes
    SecretMetadata,
    SecretResult,
    # Protocol for custom HTTP clients
    VaultHTTPClient,
    # Exceptions
    SecretsError,
    VaultConnectionError,
    SecretNotFoundError,
    SecretAccessDeniedError,
)

from yoda_foundation.security.secrets.aws_secrets import (
    # Main client
    AWSSecretsManager,
    # Configuration
    AWSSecretsConfig,
    # Data classes
    AWSSecretMetadata,
    # Exceptions
    AWSSecretsError,
    AWSSecretsConnectionError,
    AWSSecretNotFoundError,
    AWSSecretAccessDeniedError,
    AWSSecretRotationError,
)

from yoda_foundation.security.secrets.azure_keyvault import (
    # Main client
    AzureKeyVaultClient,
    # Configuration
    AzureKeyVaultConfig,
    # Data classes
    AzureSecretMetadata,
    # Exceptions
    AzureKeyVaultError,
    AzureKeyVaultConnectionError,
    AzureSecretNotFoundError,
    AzureSecretAccessDeniedError,
    AzureSecretDeletedError,
)

__all__ = [
    # Vault Client
    "VaultClient",
    # Vault Configuration
    "VaultConfig",
    "AuthMethod",
    # Vault Data classes
    "SecretMetadata",
    "SecretResult",
    # Vault Protocol
    "VaultHTTPClient",
    # Vault Exceptions
    "SecretsError",
    "VaultConnectionError",
    "SecretNotFoundError",
    "SecretAccessDeniedError",
    # AWS Secrets Manager Client
    "AWSSecretsManager",
    # AWS Configuration
    "AWSSecretsConfig",
    # AWS Data classes
    "AWSSecretMetadata",
    # AWS Exceptions
    "AWSSecretsError",
    "AWSSecretsConnectionError",
    "AWSSecretNotFoundError",
    "AWSSecretAccessDeniedError",
    "AWSSecretRotationError",
    # Azure Key Vault Client
    "AzureKeyVaultClient",
    # Azure Configuration
    "AzureKeyVaultConfig",
    # Azure Data classes
    "AzureSecretMetadata",
    # Azure Exceptions
    "AzureKeyVaultError",
    "AzureKeyVaultConnectionError",
    "AzureSecretNotFoundError",
    "AzureSecretAccessDeniedError",
    "AzureSecretDeletedError",
]
