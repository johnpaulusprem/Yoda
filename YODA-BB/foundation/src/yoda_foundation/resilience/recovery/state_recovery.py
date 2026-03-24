"""
State recovery for resuming failed operations.

This module provides state recovery mechanisms to resume operations
from checkpoints after failures.

Example:
    ```python
    from yoda_foundation.resilience.recovery import StateRecovery

    recovery = StateRecovery()

    # Execute with recovery
    result = await recovery.execute_with_recovery(
        func=long_running_task,
        checkpoint_id="task_123",
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.resilience.recovery.checkpoint_manager import CheckpointManager
from yoda_foundation.security.context import SecurityContext


T = TypeVar("T")

logger = logging.getLogger(__name__)


class StateRecovery:
    """
    State recovery manager.

    Manages state recovery for long-running operations,
    allowing resumption from checkpoints after failures.

    Attributes:
        checkpoint_manager: The checkpoint manager for state persistence.

    Example:
        ```python
        recovery = StateRecovery(
            checkpoint_manager=checkpoint_mgr,
        )

        # Execute with automatic checkpointing and recovery
        result = await recovery.execute_with_recovery(
            func=process_items,
            checkpoint_id="batch_process_123",
            checkpoint_interval=100,  # Checkpoint every 100 operations
            security_context=context,
        )
        ```
    """

    def __init__(
        self,
        checkpoint_manager: CheckpointManager | None = None,
    ) -> None:
        """
        Initialize state recovery.

        Args:
            checkpoint_manager: Checkpoint manager (creates default if not provided)
        """
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()

    async def execute_with_recovery(
        self,
        func: Callable[..., Awaitable[T]],
        checkpoint_id: str,
        security_context: SecurityContext,
        args: tuple[Any, ...] = (),
        kwargs: dict | None = None,
        auto_checkpoint: bool = True,
    ) -> T:
        """
        Execute function with state recovery.

        Args:
            func: Function to execute
            checkpoint_id: Checkpoint identifier
            security_context: Security context
            args: Function arguments
            kwargs: Function keyword arguments
            auto_checkpoint: Whether to auto-save checkpoints

        Returns:
            Function result

        Raises:
            StateRecoveryError: If recovery fails

        Example:
            ```python
            result = await recovery.execute_with_recovery(
                func=process_data,
                checkpoint_id="process_123",
                security_context=context,
            )
            ```
        """
        kwargs = kwargs or {}

        # Try to restore from checkpoint
        restored_state = None
        try:
            restored_state = await self.checkpoint_manager.restore_checkpoint(
                checkpoint_id=checkpoint_id,
                security_context=security_context,
            )

            if restored_state:
                logger.info(
                    f"Restored state from checkpoint: {checkpoint_id}",
                    extra={"checkpoint_id": checkpoint_id},
                )
                # Add restored state to kwargs
                kwargs["_recovered_state"] = restored_state

        except (
            AgenticBaseException,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
        ) as e:
            logger.warning(
                f"Failed to restore checkpoint: {e!s}",
                extra={"checkpoint_id": checkpoint_id},
            )

        # Execute function
        try:
            result = await func(*args, **kwargs)

            # Clear checkpoint on success
            if auto_checkpoint:
                await self.checkpoint_manager.delete_checkpoint(
                    checkpoint_id=checkpoint_id,
                    security_context=security_context,
                )

            return result

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
            logger.error(
                f"Execution failed: {e!s}",
                extra={"checkpoint_id": checkpoint_id},
            )
            raise

    async def save_recovery_point(
        self,
        checkpoint_id: str,
        state: dict[str, Any],
        security_context: SecurityContext,
    ) -> None:
        """
        Manually save recovery point.

        Args:
            checkpoint_id: Checkpoint identifier
            state: State to save
            security_context: Security context

        Example:
            ```python
            await recovery.save_recovery_point(
                checkpoint_id="task_123",
                state={"progress": 0.5, "items_processed": 500},
                security_context=context,
            )
            ```
        """
        await self.checkpoint_manager.save_checkpoint(
            checkpoint_id=checkpoint_id,
            state=state,
            security_context=security_context,
        )
