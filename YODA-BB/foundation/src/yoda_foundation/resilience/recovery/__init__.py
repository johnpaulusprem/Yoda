"""
Recovery mechanisms for resilient operations.

Provides state recovery, checkpoint management, and recovery procedures.

Example:
    ```python
    from yoda_foundation.resilience.recovery import (
        StateRecovery,
        CheckpointManager,
        RecoveryManager,
    )

    # Create checkpoint manager
    checkpoint_mgr = CheckpointManager()

    # Save checkpoint
    await checkpoint_mgr.save_checkpoint(
        checkpoint_id="task_123",
        state={"step": 5, "data": "..."},
        security_context=context,
    )

    # Restore from checkpoint
    state = await checkpoint_mgr.restore_checkpoint(
        checkpoint_id="task_123",
        security_context=context,
    )

    # Use recovery manager
    recovery_mgr = RecoveryManager(checkpoint_manager=checkpoint_mgr)
    recovery_mgr.register_procedure(
        name="database",
        recovery_func=recover_database,
    )

    result = await recovery_mgr.recover(
        name="database",
        security_context=context,
    )
    ```
"""

from yoda_foundation.resilience.recovery.checkpoint_manager import (
    Checkpoint,
    CheckpointManager,
)
from yoda_foundation.resilience.recovery.recovery_manager import (
    RecoveryAttempt,
    RecoveryManager,
    RecoveryProcedure,
    RecoveryResult,
    RecoveryStatus,
)
from yoda_foundation.resilience.recovery.state_recovery import StateRecovery


__all__ = [
    "Checkpoint",
    "CheckpointManager",
    "RecoveryAttempt",
    "RecoveryManager",
    "RecoveryProcedure",
    "RecoveryResult",
    "RecoveryStatus",
    "StateRecovery",
]
