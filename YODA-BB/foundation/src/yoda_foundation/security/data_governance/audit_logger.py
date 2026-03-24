"""
Audit logging module for the Agentic AI Component Library.

Provides immutable, tamper-evident audit logging for security,
compliance, and forensic analysis.

Example:
    ```python
    from yoda_foundation.security.data_governance import (
        AuditLogger,
        AuditEntry,
        AuditAction,
        AuditTrail,
    )

    # Initialize audit logger
    audit = AuditLogger()

    # Log an access event
    await audit.log_access(
        resource_type="document",
        resource_id="doc_123",
        action=AuditAction.READ,
        security_context=context,
        metadata={"classification": "CONFIDENTIAL"},
    )

    # Log a modification
    await audit.log_modification(
        resource_type="user",
        resource_id="user_456",
        action=AuditAction.UPDATE,
        changes={"email": "new@example.com"},
        security_context=context,
    )

    # Query audit trail
    trail = await audit.query(
        resource_id="doc_123",
        start_date=datetime(2024, 1, 1),
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from yoda_foundation.security.context import SecurityContext
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


class AuditAction(Enum):
    """
    Standard audit action types.

    Attributes:
        CREATE: Resource creation
        READ: Resource access/read
        UPDATE: Resource modification
        DELETE: Resource deletion
        EXECUTE: Operation execution
        LOGIN: User authentication
        LOGOUT: User session termination
        GRANT: Permission/access granted
        REVOKE: Permission/access revoked
        EXPORT: Data export
        IMPORT: Data import
        CLASSIFY: Data classification
        MASK: Data masking
        PURGE: Data purge/deletion
    """

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    LOGIN = "login"
    LOGOUT = "logout"
    GRANT = "grant"
    REVOKE = "revoke"
    EXPORT = "export"
    IMPORT = "import"
    CLASSIFY = "classify"
    MASK = "mask"
    PURGE = "purge"


class AuditStatus(Enum):
    """
    Status of audited operation.

    Attributes:
        SUCCESS: Operation completed successfully
        FAILURE: Operation failed
        DENIED: Access denied
        PARTIAL: Partially completed
    """

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    PARTIAL = "partial"


@dataclass
class AuditEntry:
    """
    Immutable audit log entry.

    Records who did what, when, where, and how for security
    and compliance auditing.

    Attributes:
        entry_id: Unique entry identifier
        timestamp: When the action occurred (UTC)
        user_id: Who performed the action
        tenant_id: Tenant identifier
        session_id: Session identifier
        correlation_id: Request correlation ID
        action: What action was performed
        resource_type: Type of resource accessed
        resource_id: Specific resource identifier
        status: Result of the operation
        ip_address: Source IP address
        user_agent: Client user agent
        changes: Before/after values for modifications
        metadata: Additional context
        previous_hash: Hash of previous entry (for chain)
        entry_hash: Hash of this entry (for tamper detection)

    Example:
        ```python
        entry = AuditEntry(
            entry_id="audit_123",
            timestamp=datetime.now(timezone.utc),
            user_id="user_456",
            action=AuditAction.UPDATE,
            resource_type="document",
            resource_id="doc_789",
            status=AuditStatus.SUCCESS,
            changes={
                "title": {"old": "Draft", "new": "Final"},
            },
        )
        ```
    """

    entry_id: str
    timestamp: datetime
    user_id: str
    action: AuditAction
    resource_type: str
    resource_id: str
    status: AuditStatus
    tenant_id: str | None = None
    session_id: str | None = None
    correlation_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    changes: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    previous_hash: str | None = None
    entry_hash: str | None = None

    def __post_init__(self) -> None:
        """Generate entry hash after initialization."""
        if self.entry_hash is None:
            object.__setattr__(self, "entry_hash", self._compute_hash())

    def _compute_hash(self) -> str:
        """
        Compute tamper-evident hash of entry.

        Creates a SHA-256 hash of the entry content for integrity verification.

        Returns:
            Hex string of hash
        """
        # Build canonical representation
        data = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "action": self.action.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "status": self.status.value,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "changes": self.changes,
            "metadata": self.metadata,
            "previous_hash": self.previous_hash,
        }

        # Create deterministic JSON
        canonical = json.dumps(data, sort_keys=True, default=str)

        # Compute hash
        return hashlib.sha256(canonical.encode()).hexdigest()

    def verify_integrity(self) -> bool:
        """
        Verify entry has not been tampered with.

        Returns:
            True if entry hash matches computed hash
        """
        computed = self._compute_hash()
        return computed == self.entry_hash

    def verify_chain(self, previous_entry: AuditEntry | None) -> bool:
        """
        Verify this entry properly chains to previous entry.

        Args:
            previous_entry: Previous entry in chain

        Returns:
            True if chain is valid
        """
        if previous_entry is None:
            # First entry should have no previous hash
            return self.previous_hash is None

        # Check if previous hash matches
        return self.previous_hash == previous_entry.entry_hash

    def to_dict(self) -> dict[str, Any]:
        """
        Convert entry to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "action": self.action.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "status": self.status.value,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "changes": self.changes,
            "metadata": self.metadata,
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEntry:
        """
        Create entry from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            AuditEntry instance
        """
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        return cls(
            entry_id=data["entry_id"],
            timestamp=timestamp or datetime.now(UTC),
            user_id=data["user_id"],
            tenant_id=data.get("tenant_id"),
            session_id=data.get("session_id"),
            correlation_id=data.get("correlation_id"),
            action=AuditAction(data["action"]),
            resource_type=data["resource_type"],
            resource_id=data["resource_id"],
            status=AuditStatus(data["status"]),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            changes=data.get("changes", {}),
            metadata=data.get("metadata", {}),
            previous_hash=data.get("previous_hash"),
            entry_hash=data.get("entry_hash"),
        )


class AuditStorage(ABC):
    """
    Abstract interface for audit log storage.

    Implement this interface to integrate with different
    storage backends (database, file, cloud service).
    """

    @abstractmethod
    async def write_entry(
        self,
        entry: AuditEntry,
        security_context: SecurityContext,
    ) -> bool:
        """
        Write audit entry to storage.

        Args:
            entry: Audit entry to write
            security_context: Security context

        Returns:
            True if written successfully
        """
        pass

    @abstractmethod
    async def get_entry(
        self,
        entry_id: str,
        security_context: SecurityContext,
    ) -> AuditEntry | None:
        """
        Retrieve audit entry by ID.

        Args:
            entry_id: Entry identifier
            security_context: Security context

        Returns:
            AuditEntry if found, None otherwise
        """
        pass

    @abstractmethod
    async def query_entries(
        self,
        filters: dict[str, Any],
        security_context: SecurityContext,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry]:
        """
        Query audit entries with filters.

        Args:
            filters: Query filters
            security_context: Security context
            limit: Maximum entries to return
            offset: Number of entries to skip

        Returns:
            List of matching audit entries
        """
        pass

    @abstractmethod
    async def get_latest_entry(
        self,
        security_context: SecurityContext,
    ) -> AuditEntry | None:
        """
        Get the most recent audit entry.

        Args:
            security_context: Security context

        Returns:
            Latest AuditEntry if any exist
        """
        pass


class InMemoryAuditStorage(AuditStorage):
    """
    In-memory audit storage for testing and development.

    Note: Not suitable for production use - data is lost on restart.
    """

    def __init__(self) -> None:
        """Initialize in-memory storage."""
        self.entries: dict[str, AuditEntry] = {}
        self.entries_list: list[AuditEntry] = []

    async def write_entry(
        self,
        entry: AuditEntry,
        security_context: SecurityContext,
    ) -> bool:
        """Write entry to memory."""
        self.entries[entry.entry_id] = entry
        self.entries_list.append(entry)
        return True

    async def get_entry(
        self,
        entry_id: str,
        security_context: SecurityContext,
    ) -> AuditEntry | None:
        """Get entry from memory."""
        return self.entries.get(entry_id)

    async def query_entries(
        self,
        filters: dict[str, Any],
        security_context: SecurityContext,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry]:
        """Query entries from memory."""
        results = []

        for entry in self.entries_list:
            # Apply filters
            match = True

            for key, value in filters.items():
                if (
                    (key == "user_id" and entry.user_id != value)
                    or (key == "resource_id" and entry.resource_id != value)
                    or (key == "resource_type" and entry.resource_type != value)
                    or (key == "action" and entry.action != value)
                    or (key == "start_date" and entry.timestamp < value)
                    or (key == "end_date" and entry.timestamp > value)
                ):
                    match = False
                    break

            if match:
                results.append(entry)

        # Apply pagination
        return results[offset : offset + limit]

    async def get_latest_entry(
        self,
        security_context: SecurityContext,
    ) -> AuditEntry | None:
        """Get latest entry from memory."""
        if not self.entries_list:
            return None
        return self.entries_list[-1]


@dataclass
class AuditTrail:
    """
    Collection of related audit entries.

    Represents a sequence of audit entries for a resource
    or operation, maintaining chain integrity.

    Attributes:
        entries: List of audit entries
        is_valid: Whether the chain is valid
        broken_links: Indices where chain is broken
    """

    entries: list[AuditEntry]
    is_valid: bool = True
    broken_links: list[int] = field(default_factory=list)

    def verify_integrity(self) -> bool:
        """
        Verify integrity of entire trail.

        Checks each entry's hash and chain linkage.

        Returns:
            True if all entries are valid and properly chained
        """
        self.is_valid = True
        self.broken_links = []

        for i, entry in enumerate(self.entries):
            # Verify entry hash
            if not entry.verify_integrity():
                self.is_valid = False
                self.broken_links.append(i)
                continue

            # Verify chain
            previous_entry = self.entries[i - 1] if i > 0 else None
            if not entry.verify_chain(previous_entry):
                self.is_valid = False
                self.broken_links.append(i)

        return self.is_valid

    def to_dict(self) -> dict[str, Any]:
        """Convert trail to dictionary."""
        return {
            "entry_count": len(self.entries),
            "is_valid": self.is_valid,
            "broken_links": self.broken_links,
            "entries": [entry.to_dict() for entry in self.entries],
        }


class AuditLogger:
    """
    Comprehensive audit logging system.

    Provides tamper-evident, immutable audit logging with
    cryptographic hash chaining for integrity verification.

    Attributes:
        storage: Audit storage backend
        enable_chaining: Whether to chain entries with hashes

    Example:
        ```python
        # Initialize logger
        audit = AuditLogger()

        # Log various events
        await audit.log_access(
            resource_type="document",
            resource_id="doc_123",
            action=AuditAction.READ,
            security_context=context,
        )

        await audit.log_modification(
            resource_type="user",
            resource_id="user_456",
            action=AuditAction.UPDATE,
            changes={"email": "new@example.com"},
            security_context=context,
        )

        await audit.log_deletion(
            resource_type="file",
            resource_id="file_789",
            security_context=context,
        )

        # Query audit trail
        trail = await audit.query(
            resource_type="document",
            start_date=datetime(2024, 1, 1),
            security_context=context,
        )

        # Verify integrity
        if trail.verify_integrity():
            print("Audit trail is valid")
        else:
            print(f"Chain broken at indices: {trail.broken_links}")
        ```
    """

    def __init__(
        self,
        storage: AuditStorage | None = None,
        enable_chaining: bool = True,
    ) -> None:
        """
        Initialize audit logger.

        Args:
            storage: Audit storage backend (uses in-memory if not provided)
            enable_chaining: Whether to chain entries with hashes
        """
        self.storage = storage or InMemoryAuditStorage()
        self.enable_chaining = enable_chaining
        self._chain_lock = asyncio.Lock()

    async def log(
        self,
        action: AuditAction,
        resource_type: str,
        resource_id: str,
        status: AuditStatus,
        security_context: SecurityContext,
        changes: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditEntry:
        """
        Log an audit entry.

        Args:
            action: Action performed
            resource_type: Type of resource
            resource_id: Resource identifier
            status: Operation status
            security_context: Security context
            changes: Before/after changes
            metadata: Additional metadata
            ip_address: Source IP address
            user_agent: Client user agent

        Returns:
            Created AuditEntry

        Example:
            ```python
            entry = await audit.log(
                action=AuditAction.UPDATE,
                resource_type="document",
                resource_id="doc_123",
                status=AuditStatus.SUCCESS,
                security_context=context,
                changes={"title": {"old": "Draft", "new": "Final"}},
                metadata={"classification": "CONFIDENTIAL"},
            )
            ```
        """
        # Use lock to ensure atomic read-then-write for hash chain integrity
        async with self._chain_lock:
            # Get previous entry for chaining
            previous_hash = None
            if self.enable_chaining:
                latest = await self.storage.get_latest_entry(security_context)
                if latest:
                    previous_hash = latest.entry_hash

            # Create entry
            entry = AuditEntry(
                entry_id=f"audit_{uuid4().hex[:16]}",
                timestamp=datetime.now(UTC),
                user_id=security_context.user_id,
                tenant_id=security_context.tenant_id,
                session_id=security_context.session_id,
                correlation_id=security_context.correlation_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                status=status,
                changes=changes or {},
                metadata=metadata or {},
                ip_address=ip_address,
                user_agent=user_agent,
                previous_hash=previous_hash,
            )

            # Write to storage
            await self.storage.write_entry(entry, security_context)

        logger.debug(
            "Audit entry created",
            entry_id=entry.entry_id,
            action=action.value,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=security_context.user_id,
        )

        return entry

    async def log_access(
        self,
        resource_type: str,
        resource_id: str,
        action: AuditAction,
        security_context: SecurityContext,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """
        Log a resource access event.

        Args:
            resource_type: Type of resource accessed
            resource_id: Resource identifier
            action: Access action (typically READ)
            security_context: Security context
            metadata: Additional metadata

        Returns:
            Created AuditEntry
        """
        return await self.log(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=AuditStatus.SUCCESS,
            security_context=security_context,
            metadata=metadata,
        )

    async def log_modification(
        self,
        resource_type: str,
        resource_id: str,
        action: AuditAction,
        changes: dict[str, Any],
        security_context: SecurityContext,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """
        Log a resource modification event.

        Args:
            resource_type: Type of resource modified
            resource_id: Resource identifier
            action: Modification action (CREATE, UPDATE, DELETE)
            changes: Before/after values
            security_context: Security context
            metadata: Additional metadata

        Returns:
            Created AuditEntry
        """
        return await self.log(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=AuditStatus.SUCCESS,
            security_context=security_context,
            changes=changes,
            metadata=metadata,
        )

    async def log_deletion(
        self,
        resource_type: str,
        resource_id: str,
        security_context: SecurityContext,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """
        Log a resource deletion event.

        Args:
            resource_type: Type of resource deleted
            resource_id: Resource identifier
            security_context: Security context
            metadata: Additional metadata

        Returns:
            Created AuditEntry
        """
        return await self.log(
            action=AuditAction.DELETE,
            resource_type=resource_type,
            resource_id=resource_id,
            status=AuditStatus.SUCCESS,
            security_context=security_context,
            metadata=metadata,
        )

    async def log_failure(
        self,
        action: AuditAction,
        resource_type: str,
        resource_id: str,
        security_context: SecurityContext,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """
        Log a failed operation.

        Args:
            action: Action that failed
            resource_type: Type of resource
            resource_id: Resource identifier
            security_context: Security context
            error: Error message
            metadata: Additional metadata

        Returns:
            Created AuditEntry
        """
        metadata = metadata or {}
        metadata["error"] = error

        return await self.log(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=AuditStatus.FAILURE,
            security_context=security_context,
            metadata=metadata,
        )

    async def query(
        self,
        security_context: SecurityContext,
        resource_type: str | None = None,
        resource_id: str | None = None,
        user_id: str | None = None,
        action: AuditAction | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AuditTrail:
        """
        Query audit entries.

        Args:
            security_context: Security context
            resource_type: Filter by resource type
            resource_id: Filter by resource ID
            user_id: Filter by user ID
            action: Filter by action
            start_date: Filter by start date
            end_date: Filter by end date
            limit: Maximum entries to return
            offset: Number of entries to skip

        Returns:
            AuditTrail with matching entries

        Raises:
            AuthorizationError: If user lacks audit query permission

        Example:
            ```python
            # Query all modifications to a document
            trail = await audit.query(
                resource_type="document",
                resource_id="doc_123",
                action=AuditAction.UPDATE,
                security_context=context,
            )

            # Query all actions by a user
            user_trail = await audit.query(
                user_id="user_456",
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
                security_context=context,
            )
            ```
        """
        security_context.require_permission("audit.query")

        # Build filters
        filters = {}
        if resource_type:
            filters["resource_type"] = resource_type
        if resource_id:
            filters["resource_id"] = resource_id
        if user_id:
            filters["user_id"] = user_id
        if action:
            filters["action"] = action
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date

        logger.info(
            "Querying audit entries",
            filters=filters,
            limit=limit,
            offset=offset,
            security_context=security_context,
        )

        # Query storage
        entries = await self.storage.query_entries(
            filters=filters,
            security_context=security_context,
            limit=limit,
            offset=offset,
        )

        # Create and verify trail
        trail = AuditTrail(entries=entries)
        trail.verify_integrity()

        logger.info(
            "Audit query completed",
            entry_count=len(entries),
            is_valid=trail.is_valid,
        )

        return trail

    async def verify_entry(
        self,
        entry_id: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Verify integrity of a specific audit entry.

        Args:
            entry_id: Entry identifier
            security_context: Security context

        Returns:
            True if entry is valid and untampered

        Raises:
            AuthorizationError: If user lacks audit query permission
        """
        security_context.require_permission("audit.query")

        entry = await self.storage.get_entry(entry_id, security_context)

        if entry is None:
            logger.warning(f"Audit entry not found: {entry_id}")
            return False

        is_valid = entry.verify_integrity()

        logger.info(
            "Audit entry verified",
            entry_id=entry_id,
            is_valid=is_valid,
        )

        return is_valid
