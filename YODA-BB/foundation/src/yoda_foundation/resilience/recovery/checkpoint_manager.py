"""
Checkpoint management for state persistence.

This module provides checkpoint management for saving and restoring
operation state.

Example:
    ```python
    from yoda_foundation.resilience.recovery import CheckpointManager

    manager = CheckpointManager()

    # Save checkpoint
    await manager.save_checkpoint(
        checkpoint_id="task_123",
        state={"step": 5, "data": {...}},
        security_context=context,
    )

    # Restore checkpoint
    state = await manager.restore_checkpoint(
        checkpoint_id="task_123",
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from yoda_foundation.exceptions import (
    CheckpointError,
    StateRecoveryError,
)
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.security.context import SecurityContext


logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """
    Checkpoint data.

    Attributes:
        checkpoint_id: Checkpoint identifier
        state: Saved state
        created_at: Creation timestamp
        expires_at: Expiration timestamp
        metadata: Additional metadata

    Example:
        ```python
        checkpoint = Checkpoint(
            checkpoint_id="ckpt_123",
            state={"step": 5, "data": {...}},
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            metadata={"user_id": "user_123"},
        )

        # Convert to dict
        data = checkpoint.to_dict()
        ```
    """

    checkpoint_id: str
    state: dict[str, Any]
    created_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """
        Convert checkpoint to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "checkpoint_id": self.checkpoint_id,
            "state": self.state,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata or {},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        """
        Create checkpoint from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            Checkpoint instance
        """
        # Convert timestamp strings to datetime
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        expires_at = data.get("expires_at")
        if expires_at and isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)

        return cls(
            checkpoint_id=data["checkpoint_id"],
            state=data["state"],
            created_at=created_at,
            expires_at=expires_at,
            metadata=data.get("metadata"),
        )


class CheckpointManager:
    """
    Checkpoint manager for state persistence.

    Manages saving, restoring, and cleaning up checkpoints
    for operation state.

    Attributes:
        default_ttl_seconds: Default time-to-live for checkpoints.
        storage_backend: Custom storage backend, if provided.

    Example:
        ```python
        manager = CheckpointManager(
            default_ttl_seconds=3600,  # 1 hour
        )

        # Save checkpoint
        await manager.save_checkpoint(
            checkpoint_id="operation_123",
            state={
                "current_step": 5,
                "processed_items": 1000,
                "partial_results": [...],
            },
            security_context=context,
        )

        # Restore checkpoint
        state = await manager.restore_checkpoint(
            checkpoint_id="operation_123",
            security_context=context,
        )

        if state:
            # Resume from checkpoint
            current_step = state["current_step"]
            ...
        ```
    """

    def __init__(
        self,
        default_ttl_seconds: int = 3600,
        storage_backend: Any | None = None,
    ) -> None:
        """
        Initialize checkpoint manager.

        Args:
            default_ttl_seconds: Default time-to-live for checkpoints
            storage_backend: Custom storage backend (uses in-memory if not provided)
        """
        self.default_ttl_seconds = default_ttl_seconds
        self.storage_backend = storage_backend

        # In-memory storage (for demonstration)
        self._checkpoints: dict[str, Checkpoint] = {}
        self._lock = asyncio.Lock()

    async def save_checkpoint(
        self,
        checkpoint_id: str,
        state: dict[str, Any],
        security_context: SecurityContext,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Save checkpoint.

        Args:
            checkpoint_id: Checkpoint identifier
            state: State to save
            security_context: Security context
            ttl_seconds: Time-to-live in seconds (uses default if not provided)
            metadata: Additional metadata

        Raises:
            CheckpointError: If checkpoint save fails

        Example:
            ```python
            await manager.save_checkpoint(
                checkpoint_id="task_123",
                state={
                    "progress": 0.75,
                    "data": {...},
                },
                ttl_seconds=7200,  # 2 hours
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_checkpoints")

        try:
            async with self._lock:
                now = datetime.now(UTC)
                ttl = ttl_seconds or self.default_ttl_seconds

                expires_at = None
                if ttl > 0:
                    expires_at = now + timedelta(seconds=ttl)

                checkpoint = Checkpoint(
                    checkpoint_id=checkpoint_id,
                    state=state,
                    created_at=now,
                    expires_at=expires_at,
                    metadata=metadata or {},
                )

                # Save to storage
                if self.storage_backend:
                    await self.storage_backend.save(checkpoint_id, checkpoint)
                else:
                    self._checkpoints[checkpoint_id] = checkpoint

                logger.info(
                    f"Saved checkpoint: {checkpoint_id}",
                    extra={
                        "checkpoint_id": checkpoint_id,
                        "ttl_seconds": ttl,
                    },
                )

        except (
            AgenticBaseException,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
        ) as e:
            raise CheckpointError(
                checkpoint_id=checkpoint_id,
                checkpoint_type="state",
                reason=f"Failed to save checkpoint: {e!s}",
                cause=e,
            )

    async def restore_checkpoint(
        self,
        checkpoint_id: str,
        security_context: SecurityContext,
    ) -> dict[str, Any] | None:
        """
        Restore checkpoint.

        Args:
            checkpoint_id: Checkpoint identifier
            security_context: Security context

        Returns:
            Restored state or None if not found

        Raises:
            StateRecoveryError: If checkpoint restore fails

        Example:
            ```python
            state = await manager.restore_checkpoint(
                checkpoint_id="task_123",
                security_context=context,
            )

            if state:
                print(f"Restored state: {state}")
            else:
                print("No checkpoint found")
            ```
        """
        security_context.require_permission("resilience.view_checkpoints")

        try:
            async with self._lock:
                # Load from storage
                if self.storage_backend:
                    checkpoint = await self.storage_backend.load(checkpoint_id)
                else:
                    checkpoint = self._checkpoints.get(checkpoint_id)

                if not checkpoint:
                    logger.info(f"No checkpoint found: {checkpoint_id}")
                    return None

                # Check expiration
                if checkpoint.expires_at:
                    now = datetime.now(UTC)
                    if now > checkpoint.expires_at:
                        logger.warning(
                            f"Checkpoint expired: {checkpoint_id}",
                            extra={"checkpoint_id": checkpoint_id},
                        )
                        # Clean up expired checkpoint
                        await self._delete_checkpoint_internal(checkpoint_id)
                        return None

                logger.info(
                    f"Restored checkpoint: {checkpoint_id}",
                    extra={"checkpoint_id": checkpoint_id},
                )

                return checkpoint.state

        except (
            AgenticBaseException,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
        ) as e:
            raise StateRecoveryError(
                checkpoint_id=checkpoint_id,
                state_type="checkpoint",
                reason=f"Failed to restore checkpoint: {e!s}",
                cause=e,
            )

    async def delete_checkpoint(
        self,
        checkpoint_id: str,
        security_context: SecurityContext,
    ) -> None:
        """
        Delete checkpoint.

        Args:
            checkpoint_id: Checkpoint identifier
            security_context: Security context

        Example:
            ```python
            await manager.delete_checkpoint(
                checkpoint_id="task_123",
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_checkpoints")

        async with self._lock:
            await self._delete_checkpoint_internal(checkpoint_id)

    async def _delete_checkpoint_internal(self, checkpoint_id: str) -> None:
        """
        Delete checkpoint without acquiring lock.

        Internal method for checkpoint deletion that assumes the caller
        already holds the lock. Used by public methods and cleanup operations.

        Args:
            checkpoint_id: The identifier of the checkpoint to delete.
        """
        if self.storage_backend:
            await self.storage_backend.delete(checkpoint_id)
        elif checkpoint_id in self._checkpoints:
            del self._checkpoints[checkpoint_id]

        logger.info(f"Deleted checkpoint: {checkpoint_id}")

    async def list_checkpoints(
        self,
        security_context: SecurityContext,
        prefix: str | None = None,
    ) -> list[str]:
        """
        List checkpoints.

        Args:
            security_context: Security context
            prefix: Optional prefix filter

        Returns:
            List of checkpoint IDs

        Example:
            ```python
            checkpoints = await manager.list_checkpoints(
                prefix="task_",
                security_context=context,
            )
            print(f"Found {len(checkpoints)} checkpoints")
            ```
        """
        security_context.require_permission("resilience.view_checkpoints")

        async with self._lock:
            if self.storage_backend:
                return await self.storage_backend.list(prefix)
            else:
                all_ids = list(self._checkpoints.keys())
                if prefix:
                    return [id for id in all_ids if id.startswith(prefix)]
                return all_ids

    async def cleanup_expired(
        self,
        security_context: SecurityContext,
    ) -> int:
        """
        Clean up expired checkpoints.

        Args:
            security_context: Security context

        Returns:
            Number of checkpoints deleted

        Example:
            ```python
            deleted = await manager.cleanup_expired(security_context=context)
            print(f"Cleaned up {deleted} expired checkpoints")
            ```
        """
        security_context.require_permission("resilience.manage_checkpoints")

        async with self._lock:
            now = datetime.now(UTC)
            expired = []

            if self.storage_backend:
                # Custom storage backend should handle cleanup
                return 0
            else:
                for checkpoint_id, checkpoint in self._checkpoints.items():
                    if checkpoint.expires_at and now > checkpoint.expires_at:
                        expired.append(checkpoint_id)

                for checkpoint_id in expired:
                    del self._checkpoints[checkpoint_id]

                if expired:
                    logger.info(f"Cleaned up {len(expired)} expired checkpoints")

                return len(expired)
