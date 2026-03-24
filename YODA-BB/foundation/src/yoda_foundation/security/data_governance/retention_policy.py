"""
Data retention policy module for the Agentic AI Component Library.

Provides automated data retention management including scheduled purging,
legal holds, archival, and compliance with retention requirements.

Example:
    ```python
    from yoda_foundation.security.data_governance import (
        RetentionPolicy,
        RetentionScheduler,
        DataPurger,
        RetentionAction,
    )

    # Define retention policy
    policy = RetentionPolicy(
        name="user_data_retention",
        retention_days=365,
        action=RetentionAction.ARCHIVE,
        classification_filter=SensitivityLevel.CONFIDENTIAL,
    )

    # Create scheduler
    scheduler = RetentionScheduler()
    scheduler.add_policy(policy)

    # Run purge
    result = await scheduler.run_purge(security_context=context)
    print(f"Purged {result.items_purged} items")
    ```
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from yoda_foundation.exceptions import (
    GovernanceError,
    ResourceError,
    ValidationError,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.security.data_governance.data_classification import (
    SensitivityLevel,
)
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


class RetentionAction(Enum):
    """
    Actions to take when retention period expires.

    Attributes:
        DELETE: Permanently delete the data
        ARCHIVE: Move to long-term archival storage
        ANONYMIZE: Remove PII/sensitive fields
        NOTIFY: Send notification but keep data
    """

    DELETE = "delete"
    ARCHIVE = "archive"
    ANONYMIZE = "anonymize"
    NOTIFY = "notify"


class RetentionStatus(Enum):
    """
    Status of data under retention policy.

    Attributes:
        ACTIVE: Within retention period
        EXPIRED: Past retention period, pending action
        LEGAL_HOLD: Under legal hold, cannot be deleted
        ARCHIVED: Moved to archival storage
        PURGED: Permanently deleted
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    LEGAL_HOLD = "legal_hold"
    ARCHIVED = "archived"
    PURGED = "purged"


@dataclass
class RetentionPolicy:
    """
    Data retention policy definition.

    Defines how long data should be retained and what action
    to take when the retention period expires.

    Attributes:
        name: Policy identifier
        retention_days: Number of days to retain data
        action: Action to take when retention expires
        classification_filter: Only apply to data with this classification
        category_filter: Only apply to data in these categories
        enabled: Whether policy is active
        grace_period_days: Additional days before taking action
        description: Human-readable policy description
        legal_hold_override: Whether legal holds override this policy

    Example:
        ```python
        # PII retention policy
        pii_policy = RetentionPolicy(
            name="pii_retention",
            retention_days=365,
            action=RetentionAction.ANONYMIZE,
            category_filter={"PII"},
            grace_period_days=30,
        )

        # PHI retention policy (7 years per HIPAA)
        phi_policy = RetentionPolicy(
            name="phi_retention",
            retention_days=2555,  # ~7 years
            action=RetentionAction.ARCHIVE,
            category_filter={"PHI"},
            legal_hold_override=True,
        )
        ```
    """

    name: str
    retention_days: int
    action: RetentionAction = RetentionAction.DELETE
    classification_filter: SensitivityLevel | None = None
    category_filter: set[str] | None = None
    enabled: bool = True
    grace_period_days: int = 0
    description: str = ""
    legal_hold_override: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate policy configuration."""
        if self.retention_days < 0:
            raise ValidationError(
                message=f"Retention days must be non-negative, got {self.retention_days}",
                suggestions=["Provide a valid retention period in days"],
            )

        if self.grace_period_days < 0:
            raise ValidationError(
                message=f"Grace period must be non-negative, got {self.grace_period_days}",
                suggestions=["Provide a valid grace period in days"],
            )

        # Ensure category_filter is a set
        if self.category_filter and isinstance(self.category_filter, list):
            object.__setattr__(self, "category_filter", set(self.category_filter))

    @property
    def total_retention_days(self) -> int:
        """Get total retention period including grace period."""
        return self.retention_days + self.grace_period_days

    def is_expired(self, data_age_days: int) -> bool:
        """
        Check if data has exceeded retention period.

        Args:
            data_age_days: Age of data in days

        Returns:
            True if data has exceeded retention period
        """
        return data_age_days > self.total_retention_days

    def should_apply(
        self,
        classification_level: SensitivityLevel | None = None,
        categories: set[str] | None = None,
    ) -> bool:
        """
        Check if policy should apply to data.

        Args:
            classification_level: Data sensitivity level
            categories: Data categories

        Returns:
            True if policy applies to this data
        """
        if not self.enabled:
            return False

        # Check classification filter
        if self.classification_filter is not None:
            if classification_level is None:
                return False
            if classification_level != self.classification_filter:
                return False

        # Check category filter
        if self.category_filter is not None:
            if categories is None:
                return False
            if not categories.intersection(self.category_filter):
                return False

        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert policy to dictionary."""
        return {
            "name": self.name,
            "retention_days": self.retention_days,
            "action": self.action.value,
            "classification_filter": (
                self.classification_filter.name if self.classification_filter else None
            ),
            "category_filter": (list(self.category_filter) if self.category_filter else None),
            "enabled": self.enabled,
            "grace_period_days": self.grace_period_days,
            "description": self.description,
            "legal_hold_override": self.legal_hold_override,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class LegalHold:
    """
    Legal hold preventing data deletion.

    Legal holds override retention policies to preserve data
    for litigation, investigations, or regulatory requirements.

    Attributes:
        hold_id: Unique hold identifier
        name: Human-readable hold name
        reason: Reason for legal hold
        data_filters: Filters to identify affected data
        created_by: User who created the hold
        created_at: When hold was created
        expires_at: Optional expiration date
        case_id: Related case/matter ID
        metadata: Additional hold metadata

    Example:
        ```python
        hold = LegalHold(
            hold_id="HOLD-2024-001",
            name="SEC Investigation",
            reason="Regulatory investigation into trading activity",
            data_filters={"user_id": "user_123", "date_range": "2024-01-01:2024-03-31"},
            created_by="legal@company.com",
            case_id="SEC-2024-123",
        )
        ```
    """

    hold_id: str
    name: str
    reason: str
    data_filters: dict[str, Any] = field(default_factory=dict)
    created_by: str = "system"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    case_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Check if hold is currently active."""
        if self.expires_at is None:
            return True
        return datetime.now(UTC) < self.expires_at

    def matches_data(self, data_metadata: dict[str, Any]) -> bool:
        """
        Check if hold applies to specific data.

        Args:
            data_metadata: Metadata about the data

        Returns:
            True if hold applies to this data
        """
        if not self.is_active:
            return False

        # Check each filter criterion
        for key, value in self.data_filters.items():
            if key not in data_metadata:
                return False

            data_value = data_metadata[key]

            # Handle date range filters
            if isinstance(value, str) and ":" in value:
                start, end = value.split(":")
                if not (start <= str(data_value) <= end):
                    return False
            elif data_value != value:
                return False

        return True


@dataclass
class PurgeResult:
    """
    Result of purge operation.

    Attributes:
        items_evaluated: Total items evaluated
        items_purged: Items successfully purged
        items_archived: Items archived
        items_skipped: Items skipped (legal hold, errors)
        errors: List of errors encountered
        duration_seconds: Operation duration
        started_at: When purge started
        completed_at: When purge completed
    """

    items_evaluated: int = 0
    items_purged: int = 0
    items_archived: int = 0
    items_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "items_evaluated": self.items_evaluated,
            "items_purged": self.items_purged,
            "items_archived": self.items_archived,
            "items_skipped": self.items_skipped,
            "error_count": len(self.errors),
            "errors": self.errors[:10],  # Limit errors in output
            "duration_seconds": self.duration_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (self.completed_at.isoformat() if self.completed_at else None),
        }


class DataStore(ABC):
    """
    Abstract interface for data storage backends.

    Implement this interface to integrate retention policies
    with different storage systems.
    """

    @abstractmethod
    async def query_expired_data(
        self,
        policy: RetentionPolicy,
        security_context: SecurityContext,
    ) -> list[dict[str, Any]]:
        """
        Query data that has exceeded retention period.

        Args:
            policy: Retention policy to evaluate
            security_context: Security context

        Returns:
            List of data items with metadata
        """
        pass

    @abstractmethod
    async def delete_data(
        self,
        data_id: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Permanently delete data.

        Args:
            data_id: Unique data identifier
            security_context: Security context

        Returns:
            True if deleted successfully
        """
        pass

    @abstractmethod
    async def archive_data(
        self,
        data_id: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Archive data to long-term storage.

        Args:
            data_id: Unique data identifier
            security_context: Security context

        Returns:
            True if archived successfully
        """
        pass


class DataPurger:
    """
    Executes data purge operations.

    Processes data according to retention policies, respecting
    legal holds and generating audit trails.

    Example:
        ```python
        purger = DataPurger(data_store=my_store)

        # Add legal hold
        purger.add_legal_hold(LegalHold(
            hold_id="HOLD-001",
            name="Litigation Hold",
            reason="Pending lawsuit",
        ))

        # Execute purge
        result = await purger.purge(
            policy=retention_policy,
            security_context=context,
            dry_run=True,  # Preview mode
        )
        ```
    """

    def __init__(self, data_store: DataStore) -> None:
        """
        Initialize data purger.

        Args:
            data_store: Data storage backend
        """
        self.data_store = data_store
        self.legal_holds: dict[str, LegalHold] = {}

    def add_legal_hold(self, hold: LegalHold) -> None:
        """
        Add a legal hold.

        Args:
            hold: Legal hold to add
        """
        self.legal_holds[hold.hold_id] = hold
        logger.info(
            "Legal hold added",
            hold_id=hold.hold_id,
            name=hold.name,
            case_id=hold.case_id,
        )

    def remove_legal_hold(self, hold_id: str) -> bool:
        """
        Remove a legal hold.

        Args:
            hold_id: Hold identifier to remove

        Returns:
            True if hold was removed
        """
        if hold_id in self.legal_holds:
            hold = self.legal_holds.pop(hold_id)
            logger.info(
                "Legal hold removed",
                hold_id=hold_id,
                name=hold.name,
            )
            return True
        return False

    def is_on_legal_hold(self, data_metadata: dict[str, Any]) -> bool:
        """
        Check if data is under legal hold.

        Args:
            data_metadata: Data metadata to check

        Returns:
            True if data is on legal hold
        """
        for hold in self.legal_holds.values():
            if hold.matches_data(data_metadata):
                return True
        return False

    async def purge(
        self,
        policy: RetentionPolicy,
        security_context: SecurityContext,
        dry_run: bool = False,
        batch_size: int = 100,
    ) -> PurgeResult:
        """
        Execute purge operation for a policy.

        Args:
            policy: Retention policy to execute
            security_context: Security context
            dry_run: If True, simulate without actual deletion
            batch_size: Number of items to process per batch

        Returns:
            PurgeResult with operation statistics

        Raises:
            AuthorizationError: If user lacks purge permission

        Example:
            ```python
            # Dry run to preview
            preview = await purger.purge(
                policy=policy,
                security_context=context,
                dry_run=True,
            )
            print(f"Would purge {preview.items_purged} items")

            # Execute actual purge
            result = await purger.purge(
                policy=policy,
                security_context=context,
                dry_run=False,
            )
            ```
        """
        security_context.require_permission("data.purge")

        result = PurgeResult(started_at=datetime.now(UTC))

        logger.info(
            "Starting purge operation",
            policy=policy.name,
            dry_run=dry_run,
            security_context=security_context,
        )

        try:
            # Query expired data
            expired_items = await self.data_store.query_expired_data(policy, security_context)

            result.items_evaluated = len(expired_items)

            logger.info(
                f"Found {len(expired_items)} expired items",
                policy=policy.name,
                items_count=len(expired_items),
            )

            # Process in batches
            for i in range(0, len(expired_items), batch_size):
                batch = expired_items[i : i + batch_size]

                for item in batch:
                    item_id = item.get("id")
                    item_metadata = item.get("metadata", {})

                    # Check legal hold
                    if self.is_on_legal_hold(item_metadata):
                        logger.debug(
                            f"Skipping item on legal hold: {item_id}",
                            item_id=item_id,
                        )
                        result.items_skipped += 1
                        continue

                    # Skip if policy can't override legal holds
                    if not policy.legal_hold_override and self.legal_holds:
                        result.items_skipped += 1
                        continue

                    # Execute retention action
                    try:
                        if not dry_run:
                            if policy.action == RetentionAction.DELETE:
                                await self.data_store.delete_data(item_id, security_context)
                                result.items_purged += 1

                            elif policy.action == RetentionAction.ARCHIVE:
                                await self.data_store.archive_data(item_id, security_context)
                                result.items_archived += 1

                            logger.debug(
                                f"Processed item: {item_id}",
                                item_id=item_id,
                                action=policy.action.value,
                            )
                        # Dry run - just count
                        elif policy.action == RetentionAction.DELETE:
                            result.items_purged += 1
                        elif policy.action == RetentionAction.ARCHIVE:
                            result.items_archived += 1

                    except (GovernanceError, OSError, ValueError) as e:
                        error_msg = f"Failed to process {item_id}: {e!s}"
                        result.errors.append(error_msg)
                        logger.error(error_msg, item_id=item_id, exc_info=e)

        except (GovernanceError, OSError, ValueError) as e:
            error_msg = f"Purge operation failed: {e!s}"
            result.errors.append(error_msg)
            logger.error(
                "Purge operation failed",
                policy=policy.name,
                exc_info=e,
            )

        finally:
            result.completed_at = datetime.now(UTC)
            if result.started_at:
                duration = result.completed_at - result.started_at
                result.duration_seconds = duration.total_seconds()

        logger.info(
            "Purge operation completed",
            policy=policy.name,
            dry_run=dry_run,
            items_evaluated=result.items_evaluated,
            items_purged=result.items_purged,
            items_archived=result.items_archived,
            items_skipped=result.items_skipped,
            duration_seconds=result.duration_seconds,
        )

        return result


class RetentionScheduler:
    """
    Scheduler for automated retention policy execution.

    Manages multiple retention policies and executes them
    on schedule.

    Example:
        ```python
        scheduler = RetentionScheduler(data_store=store)

        # Add policies
        scheduler.add_policy(pii_policy)
        scheduler.add_policy(phi_policy)
        scheduler.add_policy(logs_policy)

        # Run all policies
        results = await scheduler.run_all(security_context=context)

        for policy_name, result in results.items():
            print(f"{policy_name}: purged {result.items_purged} items")
        ```
    """

    def __init__(self, data_store: DataStore | None = None) -> None:
        """
        Initialize retention scheduler.

        Args:
            data_store: Data storage backend
        """
        self.data_store = data_store
        self.policies: dict[str, RetentionPolicy] = {}
        self.purger = DataPurger(data_store) if data_store else None

    def add_policy(self, policy: RetentionPolicy) -> None:
        """
        Add a retention policy.

        Args:
            policy: Retention policy to add
        """
        self.policies[policy.name] = policy
        logger.info(
            "Retention policy added",
            policy=policy.name,
            retention_days=policy.retention_days,
            action=policy.action.value,
        )

    def remove_policy(self, policy_name: str) -> bool:
        """
        Remove a retention policy.

        Args:
            policy_name: Name of policy to remove

        Returns:
            True if policy was removed
        """
        if policy_name in self.policies:
            self.policies.pop(policy_name)
            logger.info("Retention policy removed", policy=policy_name)
            return True
        return False

    def get_policy(self, policy_name: str) -> RetentionPolicy | None:
        """
        Get a retention policy by name.

        Args:
            policy_name: Name of policy

        Returns:
            RetentionPolicy if found, None otherwise
        """
        return self.policies.get(policy_name)

    async def run_all(
        self,
        security_context: SecurityContext,
        dry_run: bool = False,
    ) -> dict[str, PurgeResult]:
        """
        Run all enabled retention policies.

        Args:
            security_context: Security context
            dry_run: If True, simulate without actual deletion

        Returns:
            Dictionary mapping policy names to results

        Example:
            ```python
            results = await scheduler.run_all(
                security_context=context,
                dry_run=False,
            )

            total_purged = sum(r.items_purged for r in results.values())
            print(f"Total items purged: {total_purged}")
            ```
        """
        if not self.purger:
            raise ResourceError(
                message="No data store configured",
                suggestions=["Configure a data store before running purge"],
            )

        logger.info(
            "Running all retention policies",
            policy_count=len(self.policies),
            dry_run=dry_run,
        )

        results = {}

        for policy_name, policy in self.policies.items():
            if not policy.enabled:
                logger.debug(f"Skipping disabled policy: {policy_name}")
                continue

            try:
                result = await self.purger.purge(
                    policy=policy,
                    security_context=security_context,
                    dry_run=dry_run,
                )
                results[policy_name] = result

            except (GovernanceError, OSError, ValueError) as e:
                logger.error(
                    f"Failed to run policy: {policy_name}",
                    policy=policy_name,
                    exc_info=e,
                )
                results[policy_name] = PurgeResult(errors=[f"Policy execution failed: {e!s}"])

        logger.info(
            "All retention policies completed",
            policy_count=len(results),
            dry_run=dry_run,
        )

        return results
