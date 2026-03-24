"""
Memory decay strategies for the Agentic AI Component Library.

Provides configurable decay strategies for managing memory entry
importance over time. Supports time-based, access-based, hybrid,
and tier-specific decay approaches.

Example:
    ```python
    from yoda_foundation.memory.decay import (
        DecayManager,
        HybridDecay,
        TimeBasedDecay,
    )

    strategy = HybridDecay(time_weight=0.6, access_weight=0.4)
    manager = DecayManager(strategy=strategy)

    decayed = await manager.apply_decay(entries, security_context)
    kept, pruned = await manager.prune_decayed(entries, 0.1, security_context)
    ```
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from yoda_foundation.exceptions.memory import MemoryDecayError
from yoda_foundation.memory.schemas import MemoryEntry, MemoryTier
from yoda_foundation.security.context import SecurityContext


class DecayStrategy(ABC):
    """
    Abstract base class for memory decay strategies.

    Decay strategies compute a decay factor for each entry based on
    time, access patterns, or other criteria. The decay factor is a
    float between 0.0 (fully decayed) and 1.0 (no decay).

    Example:
        ```python
        class CustomDecay(DecayStrategy):
            async def compute_decay(
                self, entry: MemoryEntry, current_time: datetime,
            ) -> float:
                # Custom decay logic
                return 0.95
        ```
    """

    @abstractmethod
    async def compute_decay(
        self,
        entry: MemoryEntry,
        current_time: datetime,
    ) -> float:
        """
        Compute the decay factor for a single entry.

        Args:
            entry: The memory entry to compute decay for.
            current_time: Current timestamp for time-based calculations.

        Returns:
            Decay factor between 0.0 (fully decayed) and 1.0 (no decay).
        """


class TimeBasedDecay(DecayStrategy):
    """
    Exponential time-based decay strategy.

    Entries decay based on how much time has passed since creation or
    last access. Uses an exponential decay function with a configurable
    half-life.

    Attributes:
        half_life_seconds: Time in seconds for importance to halve.

    Example:
        ```python
        decay = TimeBasedDecay(half_life_seconds=3600)  # 1 hour half-life
        factor = await decay.compute_decay(entry, datetime.now(UTC))
        ```
    """

    def __init__(self, half_life_seconds: float = 3600.0) -> None:
        """
        Initialize time-based decay.

        Args:
            half_life_seconds: Time for importance to halve (default 1 hour).

        Example:
            ```python
            decay = TimeBasedDecay(half_life_seconds=7200)
            ```
        """
        self.half_life_seconds = max(1.0, half_life_seconds)

    async def compute_decay(
        self,
        entry: MemoryEntry,
        current_time: datetime,
    ) -> float:
        """
        Compute exponential time-based decay factor.

        Uses the formula: decay = 0.5 ^ (age / half_life)

        Args:
            entry: The memory entry.
            current_time: Current timestamp.

        Returns:
            Decay factor between 0.0 and 1.0.

        Example:
            ```python
            factor = await decay.compute_decay(entry, datetime.now(UTC))
            entry.importance *= factor
            ```
        """
        ref_time = entry.last_accessed or entry.created_at
        age_seconds = max(0.0, (current_time - ref_time).total_seconds())
        return math.pow(0.5, age_seconds / self.half_life_seconds)


class AccessBasedDecay(DecayStrategy):
    """
    Access frequency-based decay strategy.

    Entries that are accessed more frequently resist decay. Entries
    with zero accesses decay most aggressively.

    Attributes:
        max_accesses: Number of accesses considered to provide full
            decay resistance.

    Example:
        ```python
        decay = AccessBasedDecay(max_accesses=50)
        factor = await decay.compute_decay(entry, datetime.now(UTC))
        ```
    """

    def __init__(self, max_accesses: int = 50) -> None:
        """
        Initialize access-based decay.

        Args:
            max_accesses: Access count at which decay resistance is maximal.

        Example:
            ```python
            decay = AccessBasedDecay(max_accesses=100)
            ```
        """
        self.max_accesses = max(1, max_accesses)

    async def compute_decay(
        self,
        entry: MemoryEntry,
        current_time: datetime,
    ) -> float:
        """
        Compute access-based decay factor.

        Entries with more accesses retain more of their importance.
        Uses a logarithmic scale so initial accesses provide the most
        benefit.

        Args:
            entry: The memory entry.
            current_time: Current timestamp (unused but part of interface).

        Returns:
            Decay factor between 0.0 and 1.0.

        Example:
            ```python
            factor = await decay.compute_decay(entry, datetime.now(UTC))
            ```
        """
        if entry.access_count <= 0:
            return 0.5  # Base decay for unaccessed entries

        # Logarithmic scale: more accesses -> higher retention
        access_ratio = min(1.0, math.log1p(entry.access_count) / math.log1p(self.max_accesses))
        return 0.5 + (0.5 * access_ratio)


class HybridDecay(DecayStrategy):
    """
    Hybrid decay combining time-based and access-based strategies.

    Computes a weighted combination of time decay and access decay
    for balanced memory management.

    Attributes:
        time_weight: Weight for time-based component (0.0-1.0).
        access_weight: Weight for access-based component (0.0-1.0).
        time_decay: Underlying time decay strategy.
        access_decay: Underlying access decay strategy.

    Example:
        ```python
        decay = HybridDecay(time_weight=0.6, access_weight=0.4)
        factor = await decay.compute_decay(entry, datetime.now(UTC))
        ```
    """

    def __init__(
        self,
        time_weight: float = 0.6,
        access_weight: float = 0.4,
        half_life_seconds: float = 3600.0,
        max_accesses: int = 50,
    ) -> None:
        """
        Initialize hybrid decay.

        Args:
            time_weight: Weight for time-based component.
            access_weight: Weight for access-based component.
            half_life_seconds: Half-life for time-based decay.
            max_accesses: Max accesses for access-based decay.

        Example:
            ```python
            decay = HybridDecay(time_weight=0.5, access_weight=0.5)
            ```
        """
        total = time_weight + access_weight
        self.time_weight = time_weight / total if total > 0 else 0.5
        self.access_weight = access_weight / total if total > 0 else 0.5
        self.time_decay = TimeBasedDecay(half_life_seconds=half_life_seconds)
        self.access_decay = AccessBasedDecay(max_accesses=max_accesses)

    async def compute_decay(
        self,
        entry: MemoryEntry,
        current_time: datetime,
    ) -> float:
        """
        Compute hybrid decay factor.

        Args:
            entry: The memory entry.
            current_time: Current timestamp.

        Returns:
            Weighted combination of time and access decay factors.

        Example:
            ```python
            factor = await decay.compute_decay(entry, datetime.now(UTC))
            ```
        """
        time_factor = await self.time_decay.compute_decay(entry, current_time)
        access_factor = await self.access_decay.compute_decay(entry, current_time)
        return (self.time_weight * time_factor) + (self.access_weight * access_factor)


class TierSpecificDecay(DecayStrategy):
    """
    Tier-specific decay with different rates per memory tier.

    Different tiers have different natural decay rates:
    - Working: Fast decay (short-lived)
    - Episodic: Moderate decay
    - Semantic: Slow decay (knowledge persists)
    - Procedural: Very slow decay (skills are durable)

    Attributes:
        tier_half_lives: Mapping of tiers to half-life seconds.

    Example:
        ```python
        decay = TierSpecificDecay()
        factor = await decay.compute_decay(entry, datetime.now(UTC))
        ```
    """

    # Default half-lives in seconds for each tier
    DEFAULT_HALF_LIVES: dict[MemoryTier, float] = {
        MemoryTier.WORKING: 300.0,  # 5 minutes
        MemoryTier.EPISODIC: 3600.0,  # 1 hour
        MemoryTier.SEMANTIC: 86400.0,  # 24 hours
        MemoryTier.PROCEDURAL: 604800.0,  # 7 days
    }

    def __init__(
        self,
        tier_half_lives: dict[MemoryTier, float] | None = None,
    ) -> None:
        """
        Initialize tier-specific decay.

        Args:
            tier_half_lives: Optional custom half-lives per tier in seconds.
                Missing tiers use defaults.

        Example:
            ```python
            decay = TierSpecificDecay(
                tier_half_lives={MemoryTier.WORKING: 60.0},
            )
            ```
        """
        self.tier_half_lives: dict[MemoryTier, float] = dict(self.DEFAULT_HALF_LIVES)
        if tier_half_lives:
            self.tier_half_lives.update(tier_half_lives)

    async def compute_decay(
        self,
        entry: MemoryEntry,
        current_time: datetime,
    ) -> float:
        """
        Compute tier-specific decay factor.

        Uses the tier's half-life for exponential time decay.

        Args:
            entry: The memory entry.
            current_time: Current timestamp.

        Returns:
            Decay factor between 0.0 and 1.0.

        Example:
            ```python
            factor = await decay.compute_decay(entry, datetime.now(UTC))
            ```
        """
        half_life = self.tier_half_lives.get(entry.tier, 3600.0)
        half_life = max(1.0, half_life)

        ref_time = entry.last_accessed or entry.created_at
        age_seconds = max(0.0, (current_time - ref_time).total_seconds())
        return math.pow(0.5, age_seconds / half_life)


class DecayManager:
    """
    Manages memory decay operations across entries.

    Applies decay strategies to collections of entries and supports
    pruning of entries whose importance falls below a threshold.

    Attributes:
        strategy: The decay strategy to use.

    Example:
        ```python
        manager = DecayManager(strategy=HybridDecay())

        # Apply decay
        decayed_entries = await manager.apply_decay(entries, security_context)

        # Prune entries below threshold
        kept, pruned = await manager.prune_decayed(
            entries, threshold=0.1, security_context=security_context,
        )
        ```

    Raises:
        MemoryDecayError: When decay operations fail.
    """

    def __init__(self, strategy: DecayStrategy | None = None) -> None:
        """
        Initialize the decay manager.

        Args:
            strategy: Decay strategy to use. Defaults to HybridDecay.

        Example:
            ```python
            manager = DecayManager()
            manager_custom = DecayManager(strategy=TimeBasedDecay())
            ```
        """
        self.strategy = strategy or HybridDecay()

    async def apply_decay(
        self,
        entries: list[MemoryEntry],
        security_context: SecurityContext,
    ) -> list[MemoryEntry]:
        """
        Apply decay to a list of memory entries.

        Modifies each entry's importance in-place based on the configured
        decay strategy.

        Args:
            entries: Memory entries to apply decay to.
            security_context: Security context for the operation.

        Returns:
            The entries with updated importance values.

        Raises:
            MemoryDecayError: If decay computation fails.

        Example:
            ```python
            entries = await manager.apply_decay(entries, security_context)
            ```
        """
        if not entries:
            return entries

        try:
            now = datetime.now(UTC)
            for entry in entries:
                factor = await self.strategy.compute_decay(entry, now)
                entry.importance = max(0.0, min(1.0, entry.importance * factor))
            return entries
        except (TypeError, ValueError, AttributeError) as e:
            raise MemoryDecayError(
                message=f"Failed to apply decay: {e}",
                decay_strategy=type(self.strategy).__name__,
                affected_entries=len(entries),
                cause=e,
            ) from e

    async def prune_decayed(
        self,
        entries: list[MemoryEntry],
        threshold: float,
        security_context: SecurityContext,
    ) -> tuple[list[MemoryEntry], list[MemoryEntry]]:
        """
        Separate entries into kept and pruned based on importance threshold.

        Entries with importance below the threshold are marked for pruning.
        Does not modify the entries; returns two separate lists.

        Args:
            entries: Memory entries to evaluate.
            threshold: Importance threshold. Entries below this are pruned.
            security_context: Security context for the operation.

        Returns:
            Tuple of (kept_entries, pruned_entries).

        Raises:
            MemoryDecayError: If pruning evaluation fails.

        Example:
            ```python
            kept, pruned = await manager.prune_decayed(
                entries, threshold=0.1, security_context=security_context,
            )
            print(f"Keeping {len(kept)}, pruning {len(pruned)}")
            ```
        """
        if not entries:
            return ([], [])

        try:
            kept: list[MemoryEntry] = []
            pruned: list[MemoryEntry] = []

            for entry in entries:
                if entry.importance >= threshold:
                    kept.append(entry)
                else:
                    pruned.append(entry)

            return (kept, pruned)
        except (TypeError, ValueError, AttributeError) as e:
            raise MemoryDecayError(
                message=f"Failed to prune decayed entries: {e}",
                decay_strategy=type(self.strategy).__name__,
                affected_entries=len(entries),
                cause=e,
            ) from e
