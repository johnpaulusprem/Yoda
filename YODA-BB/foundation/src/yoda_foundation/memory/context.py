"""
Context builder for the Agentic AI Component Library memory system.

Builds context from memory entries using configurable strategies
(recency, relevance, importance, hybrid) for agent consumption.
Manages token budgets and provides scored context results.

Example:
    ```python
    from yoda_foundation.memory.context import ContextBuilder, ContextConfig
    from yoda_foundation.memory.schemas import ContextStrategy

    config = ContextConfig(
        strategy=ContextStrategy.HYBRID,
        max_tokens=4096,
        max_entries=20,
    )
    builder = ContextBuilder(config=config)
    result = await builder.build("What is the task?", entries, security_context)
    ```
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from yoda_foundation.exceptions.memory import MemoryContextError
from yoda_foundation.memory.schemas import (
    ContextResult,
    ContextStrategy,
    MemoryEntry,
)
from yoda_foundation.security.context import SecurityContext


@dataclass
class ContextConfig:
    """
    Configuration for the context builder.

    Attributes:
        strategy: Strategy for selecting and ranking entries.
        max_tokens: Maximum total tokens in the context window.
        max_entries: Maximum number of entries to include.
        recency_weight: Weight for recency scoring in hybrid mode (0.0-1.0).
        relevance_weight: Weight for relevance scoring in hybrid mode (0.0-1.0).
        importance_weight: Weight for importance scoring in hybrid mode (0.0-1.0).

    Example:
        ```python
        config = ContextConfig(
            strategy=ContextStrategy.HYBRID,
            max_tokens=4096,
            recency_weight=0.3,
            relevance_weight=0.4,
            importance_weight=0.3,
        )
        ```
    """

    strategy: ContextStrategy = ContextStrategy.HYBRID
    max_tokens: int = 4096
    max_entries: int = 20
    recency_weight: float = 0.3
    relevance_weight: float = 0.4
    importance_weight: float = 0.3


class ContextBuilder:
    """
    Builds context from memory entries for agent consumption.

    Selects and ranks memory entries using configurable strategies,
    respecting token budgets and entry limits. The hybrid strategy
    combines recency, relevance, and importance with configurable weights.

    Attributes:
        config: Context builder configuration.

    Example:
        ```python
        builder = ContextBuilder(
            config=ContextConfig(strategy=ContextStrategy.RELEVANCE),
        )
        result = await builder.build(
            query="What are the user preferences?",
            entries=all_entries,
            security_context=security_context,
        )
        for entry, score in zip(result.entries, result.relevance_scores):
            print(f"  {entry.content.content[:60]}: {score:.3f}")
        ```

    Raises:
        MemoryContextError: When context building fails.
    """

    def __init__(self, config: ContextConfig | None = None) -> None:
        """
        Initialize the context builder.

        Args:
            config: Optional configuration. Uses defaults if not provided.

        Example:
            ```python
            builder = ContextBuilder()
            builder_custom = ContextBuilder(config=ContextConfig(max_tokens=8192))
            ```
        """
        self.config = config or ContextConfig()

    async def build(
        self,
        query: str,
        entries: list[MemoryEntry],
        security_context: SecurityContext,
    ) -> ContextResult:
        """
        Build context from memory entries for the given query.

        Selects and ranks entries using the configured strategy, then
        trims to fit within token and entry limits.

        Args:
            query: The query to build context for.
            entries: Available memory entries to select from.
            security_context: Security context for the operation.

        Returns:
            ContextResult with selected entries and relevance scores.

        Raises:
            MemoryContextError: If context building fails.

        Example:
            ```python
            result = await builder.build(
                "What tasks are pending?", entries, security_context,
            )
            print(f"Selected {len(result.entries)} entries, {result.total_tokens} tokens")
            ```
        """
        if not entries:
            return ContextResult(
                entries=[],
                strategy=self.config.strategy,
                total_tokens=0,
                relevance_scores=[],
            )

        try:
            if self.config.strategy == ContextStrategy.RELEVANCE:
                scored = await self._by_relevance(query, entries)
            elif self.config.strategy == ContextStrategy.HYBRID:
                scored = await self._by_hybrid(query, entries)
            elif self.config.strategy == ContextStrategy.RECENCY:
                scored = await self._by_recency(entries)
            elif self.config.strategy == ContextStrategy.IMPORTANCE:
                scored = await self._by_importance(entries)
            else:
                scored = await self._by_hybrid(query, entries)

            # Sort by score descending
            scored.sort(key=lambda pair: pair[1], reverse=True)

            # Apply entry limit
            scored = scored[: self.config.max_entries]

            # Apply token budget
            selected: list[tuple[MemoryEntry, float]] = []
            total_tokens = 0
            for entry, score in scored:
                entry_tokens = entry.content.token_count or len(entry.content.content.split())
                if total_tokens + entry_tokens > self.config.max_tokens:
                    break
                selected.append((entry, score))
                total_tokens += entry_tokens

            return ContextResult(
                entries=[pair[0] for pair in selected],
                strategy=self.config.strategy,
                total_tokens=total_tokens,
                relevance_scores=[pair[1] for pair in selected],
            )
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            raise MemoryContextError(
                message=f"Failed to build context: {e}",
                strategy=self.config.strategy.value,
                max_tokens=self.config.max_tokens,
                cause=e,
            ) from e

    async def _by_recency(
        self,
        entries: list[MemoryEntry],
    ) -> list[tuple[MemoryEntry, float]]:
        """
        Score entries by recency (most recently created/accessed first).

        More recent entries receive higher scores. Uses a normalized
        time-based scoring where the newest entry gets 1.0 and the
        oldest gets a minimum score based on its position.

        Args:
            entries: Entries to score.

        Returns:
            List of (entry, score) tuples.
        """
        if not entries:
            return []

        now = datetime.now(UTC)
        scored: list[tuple[MemoryEntry, float]] = []

        # Use last_accessed if available, otherwise created_at
        max_age_seconds = 1.0
        for entry in entries:
            ref_time = entry.last_accessed or entry.created_at
            age_seconds = max(0.0, (now - ref_time).total_seconds())
            max_age_seconds = max(max_age_seconds, age_seconds)

        for entry in entries:
            ref_time = entry.last_accessed or entry.created_at
            age_seconds = max(0.0, (now - ref_time).total_seconds())
            # Exponential decay based on age
            recency_score = math.exp(-age_seconds / max(max_age_seconds, 1.0))
            scored.append((entry, recency_score))

        return scored

    async def _by_relevance(
        self,
        query: str,
        entries: list[MemoryEntry],
    ) -> list[tuple[MemoryEntry, float]]:
        """
        Score entries by text relevance to the query.

        Uses word overlap and substring matching to compute relevance.

        Args:
            query: Query text for relevance comparison.
            entries: Entries to score.

        Returns:
            List of (entry, score) tuples.
        """
        if not entries:
            return []

        scored: list[tuple[MemoryEntry, float]] = []
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for entry in entries:
            content_lower = entry.content.content.lower()

            if query_lower in content_lower:
                score = 1.0
            elif query_words:
                content_words = set(content_lower.split())
                overlap = query_words & content_words
                score = len(overlap) / len(query_words) if query_words else 0.0

                # Tag bonus
                tag_words: set[str] = set()
                for tag in entry.tags:
                    tag_words.update(tag.lower().split("_"))
                    tag_words.update(tag.lower().split("-"))
                    tag_words.add(tag.lower())
                tag_overlap = query_words & tag_words
                if tag_overlap:
                    score = min(1.0, score + 0.2 * len(tag_overlap) / len(query_words))
            else:
                score = 0.0

            scored.append((entry, score))

        return scored

    async def _by_importance(
        self,
        entries: list[MemoryEntry],
    ) -> list[tuple[MemoryEntry, float]]:
        """
        Score entries by their importance value.

        Simply uses the importance attribute as the score.

        Args:
            entries: Entries to score.

        Returns:
            List of (entry, score) tuples.
        """
        return [(entry, entry.importance) for entry in entries]

    async def _by_hybrid(
        self,
        query: str,
        entries: list[MemoryEntry],
    ) -> list[tuple[MemoryEntry, float]]:
        """
        Score entries using a weighted combination of all strategies.

        Combines recency, relevance, and importance scores using the
        configured weights.

        Args:
            query: Query text for relevance comparison.
            entries: Entries to score.

        Returns:
            List of (entry, score) tuples.
        """
        if not entries:
            return []

        recency_scores = await self._by_recency(entries)
        relevance_scores = await self._by_relevance(query, entries)
        importance_scores = await self._by_importance(entries)

        # Build lookup maps
        recency_map: dict[str, float] = {entry.id: score for entry, score in recency_scores}
        relevance_map: dict[str, float] = {entry.id: score for entry, score in relevance_scores}
        importance_map: dict[str, float] = {entry.id: score for entry, score in importance_scores}

        scored: list[tuple[MemoryEntry, float]] = []
        for entry in entries:
            recency = recency_map.get(entry.id, 0.0)
            relevance = relevance_map.get(entry.id, 0.0)
            importance = importance_map.get(entry.id, 0.0)

            combined = (
                self.config.recency_weight * recency
                + self.config.relevance_weight * relevance
                + self.config.importance_weight * importance
            )
            scored.append((entry, combined))

        return scored
