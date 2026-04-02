"""
Circuit breaker state management with persistence and synchronization.

This module provides state management for circuit breakers, including
persistence, multi-instance synchronization, and state history tracking.

Example:
    ```python
    from yoda_foundation.resilience.circuit_breaker import (
        CircuitStateManager,
        CircuitStateData,
    )
    from yoda_foundation.security import create_security_context

    # Create state manager
    manager = CircuitStateManager(
        backend="redis",
        sync_interval_ms=1000,
    )

    # Get circuit state
    context = create_security_context(user_id="service")
    state = await manager.get_state(
        circuit_name="api_client",
        security_context=context,
    )

    # Update state
    await manager.set_state(
        circuit_name="api_client",
        state=CircuitState.OPEN,
        security_context=context,
    )

    # Get state history
    history = await manager.get_history(
        circuit_name="api_client",
        limit=10,
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from yoda_foundation.exceptions import (
    CircuitBreakerError,
    ValidationError,
)
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.resilience.circuit_breaker.circuit_breaker import CircuitState
from yoda_foundation.security.context import SecurityContext


logger = logging.getLogger(__name__)


class StorageBackend(Enum):
    """Storage backend types for circuit state."""

    MEMORY = "memory"
    REDIS = "redis"
    DATABASE = "database"


@dataclass
class CircuitStateData:
    """
    Circuit breaker state data.

    Attributes:
        circuit_name: Name of the circuit breaker
        state: Current circuit state
        failure_count: Total failure count
        success_count: Total success count
        consecutive_failures: Consecutive failure count
        consecutive_successes: Consecutive success count
        last_failure_time: Last failure timestamp
        last_success_time: Last success timestamp
        opened_at: When circuit was opened
        last_transition: Last state transition timestamp
        metadata: Additional metadata

    Example:
        ```python
        state_data = CircuitStateData(
            circuit_name="payment_api",
            state=CircuitState.OPEN,
            failure_count=10,
            consecutive_failures=5,
            opened_at=datetime.now(timezone.utc),
        )
        ```
    """

    circuit_name: str
    state: CircuitState
    failure_count: int = 0
    success_count: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: datetime | None = None
    last_success_time: datetime | None = None
    opened_at: datetime | None = None
    last_transition: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert state data to dictionary.

        Returns:
            Dictionary representation
        """
        data = asdict(self)
        data["state"] = self.state.value
        if self.last_failure_time:
            data["last_failure_time"] = self.last_failure_time.isoformat()
        if self.last_success_time:
            data["last_success_time"] = self.last_success_time.isoformat()
        if self.opened_at:
            data["opened_at"] = self.opened_at.isoformat()
        if self.last_transition:
            data["last_transition"] = self.last_transition.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CircuitStateData:
        """
        Create state data from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            CircuitStateData instance
        """
        # Convert state string to enum
        if isinstance(data.get("state"), str):
            data["state"] = CircuitState(data["state"])

        # Convert timestamp strings to datetime
        for field_name in [
            "last_failure_time",
            "last_success_time",
            "opened_at",
            "last_transition",
        ]:
            if data.get(field_name) and isinstance(data[field_name], str):
                data[field_name] = datetime.fromisoformat(data[field_name])

        return cls(**data)


@dataclass
class StateTransition:
    """
    Circuit breaker state transition record.

    Attributes:
        circuit_name: Name of the circuit breaker
        from_state: Previous state
        to_state: New state
        timestamp: When transition occurred
        reason: Reason for transition
        metadata: Additional metadata

    Example:
        ```python
        transition = StateTransition(
            circuit_name="api_client",
            from_state=CircuitState.CLOSED,
            to_state=CircuitState.OPEN,
            timestamp=datetime.now(timezone.utc),
            reason="threshold_exceeded",
        )
        ```
    """

    circuit_name: str
    from_state: CircuitState
    to_state: CircuitState
    timestamp: datetime
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert transition to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "circuit_name": self.circuit_name,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason,
            "metadata": self.metadata,
        }


class StateStorageProtocol(Protocol):
    """Protocol for state storage backends."""

    async def get(self, key: str) -> dict[str, Any] | None:
        """Get state by key."""
        ...

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        """Set state by key."""
        ...

    async def delete(self, key: str) -> None:
        """Delete state by key."""
        ...

    async def list_keys(self, pattern: str) -> list[str]:
        """List keys matching pattern."""
        ...


class MemoryStorage:
    """
    In-memory storage backend for testing.

    Provides a simple in-memory key-value store implementing
    the StateStorageProtocol interface.

    Attributes:
        _store: Internal dictionary storing state data.
    """

    def __init__(self) -> None:
        """Initialize memory storage."""
        self._store: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        """
        Get state by key.

        Args:
            key: The storage key to retrieve.

        Returns:
            Stored state dictionary or None if not found.
        """
        return self._store.get(key)

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        """
        Set state by key.

        Args:
            key: The storage key to set.
            value: The state dictionary to store.
            ttl_seconds: Time-to-live in seconds (not implemented in memory backend).
        """
        self._store[key] = value

    async def delete(self, key: str) -> None:
        """
        Delete state by key.

        Args:
            key: The storage key to delete.
        """
        self._store.pop(key, None)

    async def list_keys(self, pattern: str) -> list[str]:
        """
        List keys matching pattern.

        Supports simple prefix matching with wildcard (*) at the end.

        Args:
            pattern: Pattern to match (e.g., "circuit:state:*").

        Returns:
            List of matching keys.
        """
        # Simple pattern matching for memory backend
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in self._store.keys() if k.startswith(prefix)]
        return [k for k in self._store.keys() if k == pattern]


class CircuitStateManager:
    """
    Circuit breaker state manager with persistence and synchronization.

    Manages circuit breaker state across multiple instances with
    configurable persistence backends and state history tracking.

    Attributes:
        backend: Storage backend type
        sync_interval_ms: State synchronization interval in milliseconds
        history_limit: Maximum history entries per circuit
        ttl_seconds: Time-to-live for state data

    Example:
        ```python
        # Create state manager
        manager = CircuitStateManager(
            backend="redis",
            sync_interval_ms=1000,
            history_limit=100,
        )

        # Get circuit state
        state = await manager.get_state(
            circuit_name="api_client",
            security_context=context,
        )

        # Transition state
        await manager.transition_state(
            circuit_name="api_client",
            to_state=CircuitState.OPEN,
            reason="threshold_exceeded",
            security_context=context,
        )

        # Get state history
        history = await manager.get_history(
            circuit_name="api_client",
            limit=10,
            security_context=context,
        )
        ```
    """

    def __init__(
        self,
        backend: str = "memory",
        sync_interval_ms: int = 1000,
        history_limit: int = 100,
        ttl_seconds: int | None = None,
        storage: StateStorageProtocol | None = None,
    ) -> None:
        """
        Initialize circuit state manager.

        Args:
            backend: Storage backend type
            sync_interval_ms: State sync interval in milliseconds
            history_limit: Maximum history entries per circuit
            ttl_seconds: State data time-to-live
            storage: Custom storage backend

        Raises:
            ValidationError: If parameters are invalid
        """
        if sync_interval_ms < 100:
            raise ValidationError(
                message=f"sync_interval_ms must be at least 100ms, got {sync_interval_ms}",
                field_name="sync_interval_ms",
            )

        if history_limit < 1:
            raise ValidationError(
                message=f"history_limit must be at least 1, got {history_limit}",
                field_name="history_limit",
            )

        self.backend = StorageBackend(backend)
        self.sync_interval_ms = sync_interval_ms
        self.history_limit = history_limit
        self.ttl_seconds = ttl_seconds

        # Initialize storage backend
        if storage:
            self._storage = storage
        elif self.backend == StorageBackend.MEMORY:
            self._storage = MemoryStorage()
        else:
            raise ValidationError(
                message=f"Unsupported backend: {backend}. Provide custom storage.",
                field_name="backend",
            )

        # Local cache
        self._cache: dict[str, CircuitStateData] = {}
        self._history: dict[str, list[StateTransition]] = {}
        self._lock = asyncio.Lock()
        self._sync_task: asyncio.Task | None = None

    async def start(self, security_context: SecurityContext) -> None:
        """
        Start state synchronization.

        Args:
            security_context: Security context

        Example:
            ```python
            await manager.start(security_context=context)
            ```
        """
        security_context.require_permission("resilience.manage_circuit_breaker")

        if self._sync_task is None or self._sync_task.done():
            self._sync_task = asyncio.create_task(self._sync_loop())
            logger.info(
                "Started circuit state synchronization",
                extra={
                    "backend": self.backend.value,
                    "sync_interval_ms": self.sync_interval_ms,
                },
            )

    async def stop(self, security_context: SecurityContext) -> None:
        """
        Stop state synchronization.

        Args:
            security_context: Security context

        Example:
            ```python
            await manager.stop(security_context=context)
            ```
        """
        security_context.require_permission("resilience.manage_circuit_breaker")

        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped circuit state synchronization")

    async def get_state(
        self,
        circuit_name: str,
        security_context: SecurityContext,
    ) -> CircuitStateData | None:
        """
        Get current circuit state.

        Args:
            circuit_name: Circuit breaker name
            security_context: Security context

        Returns:
            Current circuit state data or None if not found

        Example:
            ```python
            state = await manager.get_state(
                circuit_name="api_client",
                security_context=context,
            )
            if state and state.state == CircuitState.OPEN:
                print("Circuit is open")
            ```
        """
        security_context.require_permission("resilience.read_circuit_state")

        async with self._lock:
            # Check cache first
            if circuit_name in self._cache:
                return self._cache[circuit_name]

            # Load from storage
            key = self._get_state_key(circuit_name)
            data = await self._storage.get(key)

            if data:
                state_data = CircuitStateData.from_dict(data)
                self._cache[circuit_name] = state_data
                return state_data

            return None

    async def set_state(
        self,
        circuit_name: str,
        state: CircuitState,
        security_context: SecurityContext,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Set circuit state.

        Args:
            circuit_name: Circuit breaker name
            state: New circuit state
            security_context: Security context
            metadata: Additional metadata

        Example:
            ```python
            await manager.set_state(
                circuit_name="api_client",
                state=CircuitState.OPEN,
                security_context=context,
                metadata={"threshold": 5},
            )
            ```
        """
        security_context.require_permission("resilience.manage_circuit_breaker")

        async with self._lock:
            # Get or create state data
            state_data = self._cache.get(circuit_name)
            if state_data is None:
                state_data = CircuitStateData(
                    circuit_name=circuit_name,
                    state=state,
                )

            # Update state
            old_state = state_data.state
            state_data.state = state
            state_data.last_transition = datetime.now(UTC)
            if metadata:
                state_data.metadata.update(metadata)

            # Save to cache and storage
            self._cache[circuit_name] = state_data
            await self._persist_state(circuit_name, state_data)

            # Record transition if state changed
            if old_state != state:
                await self._record_transition(
                    circuit_name=circuit_name,
                    from_state=old_state,
                    to_state=state,
                    reason="manual_update",
                )

            logger.info(
                f"Set circuit state for '{circuit_name}'",
                extra={
                    "circuit_name": circuit_name,
                    "state": state.value,
                    "old_state": old_state.value,
                },
            )

    async def transition_state(
        self,
        circuit_name: str,
        to_state: CircuitState,
        reason: str | None = None,
        *,
        security_context: SecurityContext,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Transition circuit to a new state.

        Args:
            circuit_name: Circuit breaker name
            to_state: Target state
            reason: Reason for transition
            security_context: Security context
            metadata: Additional metadata

        Example:
            ```python
            await manager.transition_state(
                circuit_name="api_client",
                to_state=CircuitState.HALF_OPEN,
                reason="recovery_timeout_elapsed",
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_circuit_breaker")

        async with self._lock:
            # Get current state
            state_data = await self.get_state(circuit_name, security_context)
            if state_data is None:
                raise CircuitBreakerError(
                    message=f"Circuit '{circuit_name}' not found",
                    circuit_name=circuit_name,
                )

            from_state = state_data.state

            # Update state
            state_data.state = to_state
            state_data.last_transition = datetime.now(UTC)

            # Update specific fields based on transition
            if to_state == CircuitState.OPEN:
                state_data.opened_at = datetime.now(UTC)
            elif to_state == CircuitState.CLOSED:
                state_data.consecutive_failures = 0
                state_data.opened_at = None

            if metadata:
                state_data.metadata.update(metadata)

            # Save state
            self._cache[circuit_name] = state_data
            await self._persist_state(circuit_name, state_data)

            # Record transition
            await self._record_transition(
                circuit_name=circuit_name,
                from_state=from_state,
                to_state=to_state,
                reason=reason or "unknown",
            )

            logger.info(
                f"Transitioned circuit '{circuit_name}' from {from_state.value} to {to_state.value}",
                extra={
                    "circuit_name": circuit_name,
                    "from_state": from_state.value,
                    "to_state": to_state.value,
                    "reason": reason,
                },
            )

    async def update_metrics(
        self,
        circuit_name: str,
        success: bool,
        security_context: SecurityContext,
    ) -> None:
        """
        Update circuit metrics after execution.

        Args:
            circuit_name: Circuit breaker name
            success: Whether execution succeeded
            security_context: Security context

        Example:
            ```python
            # After successful call
            await manager.update_metrics(
                circuit_name="api_client",
                success=True,
                security_context=context,
            )
            ```
        """
        security_context.require_permission("resilience.manage_circuit_breaker")

        async with self._lock:
            state_data = self._cache.get(circuit_name)
            if state_data is None:
                return

            now = datetime.now(UTC)

            if success:
                state_data.success_count += 1
                state_data.consecutive_successes += 1
                state_data.consecutive_failures = 0
                state_data.last_success_time = now
            else:
                state_data.failure_count += 1
                state_data.consecutive_failures += 1
                state_data.consecutive_successes = 0
                state_data.last_failure_time = now

            await self._persist_state(circuit_name, state_data)

    async def get_history(
        self,
        circuit_name: str,
        limit: int | None = None,
        *,
        security_context: SecurityContext,
    ) -> list[StateTransition]:
        """
        Get state transition history.

        Args:
            circuit_name: Circuit breaker name
            limit: Maximum number of transitions to return
            security_context: Security context

        Returns:
            List of state transitions, most recent first

        Example:
            ```python
            history = await manager.get_history(
                circuit_name="api_client",
                limit=10,
                security_context=context,
            )
            for transition in history:
                print(f"{transition.timestamp}: {transition.from_state} -> {transition.to_state}")
            ```
        """
        security_context.require_permission("resilience.read_circuit_state")

        async with self._lock:
            transitions = self._history.get(circuit_name, [])
            if limit:
                transitions = transitions[-limit:]
            return list(reversed(transitions))

    async def _persist_state(
        self,
        circuit_name: str,
        state_data: CircuitStateData,
    ) -> None:
        """
        Persist state to storage backend.

        Args:
            circuit_name: Circuit breaker name
            state_data: State data to persist
        """
        key = self._get_state_key(circuit_name)
        await self._storage.set(key, state_data.to_dict(), ttl_seconds=self.ttl_seconds)

    async def _record_transition(
        self,
        circuit_name: str,
        from_state: CircuitState,
        to_state: CircuitState,
        reason: str,
    ) -> None:
        """
        Record state transition in history.

        Args:
            circuit_name: Circuit breaker name
            from_state: Previous state
            to_state: New state
            reason: Reason for transition
        """
        transition = StateTransition(
            circuit_name=circuit_name,
            from_state=from_state,
            to_state=to_state,
            timestamp=datetime.now(UTC),
            reason=reason,
        )

        if circuit_name not in self._history:
            self._history[circuit_name] = []

        self._history[circuit_name].append(transition)

        # Trim history
        if len(self._history[circuit_name]) > self.history_limit:
            self._history[circuit_name] = self._history[circuit_name][-self.history_limit :]

        # Persist history
        history_key = self._get_history_key(circuit_name)
        history_data = [t.to_dict() for t in self._history[circuit_name]]
        await self._storage.set(
            history_key, {"transitions": history_data}, ttl_seconds=self.ttl_seconds
        )

    async def _sync_loop(self) -> None:
        """
        Periodic state synchronization loop.

        Runs continuously to synchronize circuit breaker states from
        the storage backend at the configured sync interval. Handles
        cancellation gracefully and logs synchronization errors.

        Raises:
            asyncio.CancelledError: When the synchronization is stopped.
        """
        while True:
            try:
                await asyncio.sleep(self.sync_interval_ms / 1000.0)
                await self._sync_states()
            except asyncio.CancelledError:
                break
            except (
                AgenticBaseException,
                ConnectionError,
                TimeoutError,
                OSError,
                ValueError,
                KeyError,
            ) as e:
                logger.error(f"State sync error: {e}", exc_info=True)

    async def _sync_states(self) -> None:
        """
        Synchronize circuit breaker states from storage backend.

        Fetches all circuit state keys from storage and updates the
        local cache with any states that are newer than the cached
        versions based on last_transition timestamps.
        """
        async with self._lock:
            # Get all circuit state keys
            pattern = self._get_state_key("*")
            keys = await self._storage.list_keys(pattern)

            for key in keys:
                data = await self._storage.get(key)
                if data:
                    state_data = CircuitStateData.from_dict(data)
                    circuit_name = state_data.circuit_name

                    # Update cache if state is newer
                    cached = self._cache.get(circuit_name)
                    if cached is None or (
                        state_data.last_transition
                        and (
                            cached.last_transition is None
                            or state_data.last_transition > cached.last_transition
                        )
                    ):
                        self._cache[circuit_name] = state_data

    def _get_state_key(self, circuit_name: str) -> str:
        """
        Get storage key for circuit state.

        Args:
            circuit_name: Name of the circuit breaker.

        Returns:
            Storage key string in format "circuit:state:{circuit_name}".
        """
        return f"circuit:state:{circuit_name}"

    def _get_history_key(self, circuit_name: str) -> str:
        """
        Get storage key for circuit history.

        Args:
            circuit_name: Name of the circuit breaker.

        Returns:
            Storage key string in format "circuit:history:{circuit_name}".
        """
        return f"circuit:history:{circuit_name}"
