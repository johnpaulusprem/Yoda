"""
Auto-consolidator for Mem0-style memory management.

Implements automatic decisions about when to create, update, merge, and
promote memories based on conversation activity and configurable thresholds.
Orchestrates the conversation extractor, memory linker, and consolidation
engine to maintain a coherent, up-to-date memory graph.

Example:
    ```python
    from yoda_foundation.memory.graph_memory.auto_consolidator import (
        AutoConsolidationConfig,
        AutoConsolidator,
    )
    from yoda_foundation.memory.consolidation import ConsolidationEngine
    from yoda_foundation.memory.graph_memory.conversation_extractor import (
        ConversationMemoryExtractor,
    )
    from yoda_foundation.memory.graph_memory.memory_linker import MemoryKGLinker

    config = AutoConsolidationConfig(
        consolidation_threshold=10,
        auto_promote=True,
        min_importance_for_promotion=0.7,
    )

    consolidator = AutoConsolidator(
        consolidation_engine=ConsolidationEngine(llm_client=my_llm),
        extractor=ConversationMemoryExtractor(llm_client=my_llm),
        linker=MemoryKGLinker(),
        config=config,
    )

    result = await consolidator.process_conversation_turn(
        user_message="I just got promoted to VP of Engineering.",
        assistant_message="Congratulations on the promotion!",
        conversation_id="conv_42",
        user_id="user_123",
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from yoda_foundation.exceptions.memory import (
    MemoryConsolidationError,
    MemoryContextError,
)
from yoda_foundation.memory.consolidation import ConsolidationEngine
from yoda_foundation.memory.graph_memory.conversation_extractor import (
    ConversationMemoryExtractor,
    ConversationMemoryUpdate,
)
from yoda_foundation.memory.graph_memory.memory_linker import MemoryKGLinker
from yoda_foundation.memory.schemas import (
    ConsolidationResult,
    ConsolidationStrategy,
    MemoryContent,
    MemoryEntry,
    MemoryTier,
)
from yoda_foundation.security.context import SecurityContext


# Tier promotion order: WORKING -> EPISODIC -> SEMANTIC
_PROMOTION_PATH: dict[MemoryTier, MemoryTier] = {
    MemoryTier.WORKING: MemoryTier.EPISODIC,
    MemoryTier.EPISODIC: MemoryTier.SEMANTIC,
}


@dataclass
class AutoConsolidationConfig:
    """
    Configuration for automatic memory consolidation behaviour.

    Attributes:
        consolidation_threshold: Number of entries per tier before
            automatic consolidation is triggered.
        auto_promote: Whether to automatically promote high-importance
            entries to higher tiers.
        min_importance_for_promotion: Minimum importance score required
            for an entry to be auto-promoted.

    Example:
        ```python
        config = AutoConsolidationConfig(
            consolidation_threshold=20,
            auto_promote=True,
            min_importance_for_promotion=0.8,
        )
        ```
    """

    consolidation_threshold: int = 10
    auto_promote: bool = True
    min_importance_for_promotion: float = 0.7


class AutoConsolidator:
    """
    Mem0-style auto-consolidator for conversation-driven memory management.

    Orchestrates end-to-end processing of conversation turns: extraction
    of entities and relations, linking to the knowledge graph, optional
    consolidation when thresholds are exceeded, and tier promotion for
    high-importance entries.

    Attributes:
        consolidation_engine: Engine for consolidating memory entries.
        extractor: Conversation memory extractor.
        linker: Memory-to-KG linker.
        config: Auto-consolidation configuration.

    Example:
        ```python
        consolidator = AutoConsolidator(
            consolidation_engine=engine,
            extractor=extractor,
            linker=linker,
        )

        result = await consolidator.process_conversation_turn(
            user_message="I prefer dark mode in all apps.",
            assistant_message="Noted, I'll remember your preference.",
            conversation_id="conv_01",
            user_id="user_42",
            security_context=ctx,
        )
        print(f"Entries after: {result.consolidated_count}")
        ```

    Raises:
        MemoryConsolidationError: When extraction or consolidation fails.
        MemoryContextError: When linking or promotion fails.
    """

    def __init__(
        self,
        consolidation_engine: ConsolidationEngine,
        extractor: ConversationMemoryExtractor,
        linker: MemoryKGLinker,
        config: AutoConsolidationConfig | None = None,
    ) -> None:
        """
        Initialise the auto-consolidator.

        Args:
            consolidation_engine: Engine for running consolidation strategies.
            extractor: Conversation memory extractor for parsing turns.
            linker: Linker for connecting memories to KG entities.
            config: Optional configuration overrides. Uses defaults if
                ``None``.

        Example:
            ```python
            consolidator = AutoConsolidator(
                consolidation_engine=engine,
                extractor=extractor,
                linker=linker,
                config=AutoConsolidationConfig(consolidation_threshold=5),
            )
            ```
        """
        self._engine = consolidation_engine
        self._extractor = extractor
        self._linker = linker
        self._config = config or AutoConsolidationConfig()

        # In-memory storage for tracking entries per tier per user
        self._entries_by_user_tier: dict[str, dict[MemoryTier, list[MemoryEntry]]] = defaultdict(
            lambda: defaultdict(list)
        )

    async def process_conversation_turn(
        self,
        user_message: str,
        assistant_message: str,
        conversation_id: str,
        user_id: str,
        security_context: SecurityContext,
    ) -> ConsolidationResult:
        """
        Process a single conversation turn end-to-end.

        Steps performed:
        1. Extract entities and relations from the turn.
        2. Store resulting memory entries in the internal tracker.
        3. Link memory entries to extracted KG entities.
        4. Auto-promote high-importance entries if enabled.
        5. Trigger consolidation if the threshold is exceeded.

        Args:
            user_message: The user's message text.
            assistant_message: The assistant's response text.
            conversation_id: Unique conversation identifier.
            user_id: Unique user identifier for per-user tracking.
            security_context: Security context for authorisation.

        Returns:
            ``ConsolidationResult`` summarising the outcome. If no
            consolidation was triggered, returns a result with the
            current entry counts.

        Raises:
            MemoryConsolidationError: If extraction or consolidation fails.
            MemoryContextError: If linking fails.

        Example:
            ```python
            result = await consolidator.process_conversation_turn(
                user_message="I live in San Francisco.",
                assistant_message="Nice city!",
                conversation_id="conv_01",
                user_id="user_42",
                security_context=ctx,
            )
            ```
        """
        # Step 1: Extract from conversation turn
        try:
            update: ConversationMemoryUpdate = await self._extractor.extract_from_turn(
                user_message=user_message,
                assistant_message=assistant_message,
                conversation_id=conversation_id,
                security_context=security_context,
            )
        except MemoryConsolidationError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise MemoryConsolidationError(
                message=f"Conversation turn extraction failed: {exc}",
                strategy="auto_consolidation",
                cause=exc,
            ) from exc

        # Step 2: Store extracted memory entries
        user_tiers = self._entries_by_user_tier[user_id]
        for entry in update.memory_entries:
            user_tiers[entry.tier].append(entry)

        # Step 3: Link memories to extracted entities
        await self._link_entries_to_entities(
            entries=list(update.memory_entries),
            entities=list(update.new_entities),
            security_context=security_context,
        )

        # Step 4: Auto-promote high-importance entries
        promoted_entries: list[MemoryEntry] = []
        if self._config.auto_promote:
            for entry in update.memory_entries:
                promoted = await self.auto_tier_promote(entry, security_context)
                if promoted is not None:
                    promoted_entries.append(promoted)
                    user_tiers[promoted.tier].append(promoted)

        # Step 5: Check whether consolidation should be triggered
        all_current_entries = list(update.memory_entries) + promoted_entries
        consolidation_triggered = False
        consolidation_result: ConsolidationResult | None = None

        for tier in (MemoryTier.WORKING, MemoryTier.EPISODIC, MemoryTier.SEMANTIC):
            tier_entries = user_tiers[tier]
            if await self.should_consolidate(tier, len(tier_entries), security_context):
                try:
                    consolidation_result = await self._engine.consolidate(
                        entries=tier_entries,
                        strategy=ConsolidationStrategy.SUMMARIZE,
                        security_context=security_context,
                    )
                    # Replace tier entries with consolidated ones
                    user_tiers[tier] = list(consolidation_result.entries)
                    consolidation_triggered = True
                except MemoryConsolidationError:
                    raise
                except (ValueError, TypeError, KeyError) as exc:
                    raise MemoryConsolidationError(
                        message=f"Auto-consolidation of tier {tier.value} failed: {exc}",
                        strategy="auto_consolidation",
                        entries_count=len(tier_entries),
                        cause=exc,
                    ) from exc

        if consolidation_triggered and consolidation_result is not None:
            return consolidation_result

        # No consolidation needed -- return a summary result
        total_entries = sum(len(entries) for entries in user_tiers.values())
        return ConsolidationResult(
            original_count=len(all_current_entries),
            consolidated_count=total_entries,
            strategy=ConsolidationStrategy.EXTRACT,
            entries=all_current_entries,
            duration_ms=0,
        )

    async def should_consolidate(
        self,
        tier: MemoryTier,
        entry_count: int,
        security_context: SecurityContext,
    ) -> bool:
        """
        Determine whether consolidation should be triggered for a tier.

        Returns ``True`` when the number of entries in the tier meets or
        exceeds the configured threshold.

        Args:
            tier: The memory tier to evaluate.
            entry_count: Current number of entries in the tier.
            security_context: Security context for authorisation.

        Returns:
            ``True`` if consolidation should be triggered.

        Example:
            ```python
            if await consolidator.should_consolidate(
                tier=MemoryTier.WORKING,
                entry_count=15,
                security_context=ctx,
            ):
                print("Consolidation needed!")
            ```
        """
        return entry_count >= self._config.consolidation_threshold

    async def auto_tier_promote(
        self,
        entry: MemoryEntry,
        security_context: SecurityContext,
    ) -> MemoryEntry | None:
        """
        Promote a high-importance entry to the next tier.

        Promotion path: WORKING -> EPISODIC -> SEMANTIC.
        SEMANTIC and PROCEDURAL entries are not promoted further.

        An entry is promoted only if:
        - ``auto_promote`` is enabled in the config.
        - The entry's importance meets or exceeds ``min_importance_for_promotion``.
        - The entry's current tier has a valid promotion target.

        Args:
            entry: The memory entry to consider for promotion.
            security_context: Security context for authorisation.

        Returns:
            A new ``MemoryEntry`` at the promoted tier, or ``None`` if
            promotion criteria are not met.

        Example:
            ```python
            promoted = await consolidator.auto_tier_promote(
                entry=working_entry,
                security_context=ctx,
            )
            if promoted:
                print(f"Promoted to {promoted.tier.value}")
            ```
        """
        if not self._config.auto_promote:
            return None

        if entry.importance < self._config.min_importance_for_promotion:
            return None

        next_tier = _PROMOTION_PATH.get(entry.tier)
        if next_tier is None:
            return None

        promoted = MemoryEntry(
            id=f"mem_{uuid.uuid4().hex[:12]}",
            tier=next_tier,
            scope=entry.scope,
            content=MemoryContent(
                content=entry.content.content,
                content_type=entry.content.content_type,
                embedding=entry.content.embedding,
                metadata={
                    **entry.content.metadata,
                    "promoted_from": entry.tier.value,
                    "original_id": entry.id,
                },
                token_count=entry.content.token_count,
            ),
            importance=min(1.0, entry.importance + 0.1),
            access_count=entry.access_count,
            created_at=datetime.now(UTC),
            tags=[*entry.tags, f"promoted_from_{entry.tier.value}"],
            metadata={
                **entry.metadata,
                "promoted_from_tier": entry.tier.value,
                "promoted_from_id": entry.id,
                "promotion_timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return promoted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _link_entries_to_entities(
        self,
        entries: list[MemoryEntry],
        entities: list[dict[str, Any]],
        security_context: SecurityContext,
    ) -> None:
        """
        Link memory entries to extracted KG entities.

        Creates a link from each memory entry to each extracted entity,
        using the entity name as a pseudo entity-ID.

        Args:
            entries: Memory entries to link.
            entities: Extracted entity dicts (name, type, attributes).
            security_context: Security context for authorisation.
        """
        if not entries or not entities:
            return

        for entry in entries:
            for entity in entities:
                entity_name = entity.get("name", "")
                if not entity_name:
                    continue

                # Use a unique entity ID to avoid collisions
                entity_id = f"ent_{uuid.uuid4().hex[:12]}"

                try:
                    await self._linker.link_memory_to_entity(
                        memory_id=entry.id,
                        entity_id=entity_id,
                        link_type="mentions",
                        security_context=security_context,
                        metadata={
                            "entity_name": entity_name,
                            "entity_type": entity.get("type", "entity"),
                        },
                    )
                except MemoryContextError:
                    raise
                except (ValueError, TypeError, KeyError) as exc:
                    raise MemoryContextError(
                        message=(f"Failed to link memory {entry.id} to entity {entity_id}: {exc}"),
                        strategy="auto_link",
                        cause=exc,
                    ) from exc

    async def get_user_entry_counts(
        self,
        user_id: str,
        security_context: SecurityContext,
    ) -> dict[str, int]:
        """
        Return entry counts per tier for a given user.

        Args:
            user_id: User identifier.
            security_context: Security context for authorisation.

        Returns:
            Dictionary mapping tier value strings to entry counts.

        Example:
            ```python
            counts = await consolidator.get_user_entry_counts(
                user_id="user_42",
                security_context=ctx,
            )
            for tier, count in counts.items():
                print(f"{tier}: {count}")
            ```
        """
        user_tiers = self._entries_by_user_tier.get(user_id, {})
        return {tier.value: len(entries) for tier, entries in user_tiers.items() if entries}

    async def reset_user(
        self,
        user_id: str,
        security_context: SecurityContext,
    ) -> None:
        """
        Clear all tracked entries for a given user.

        Args:
            user_id: User identifier.
            security_context: Security context for authorisation.

        Example:
            ```python
            await consolidator.reset_user(
                user_id="user_42",
                security_context=ctx,
            )
            ```
        """
        self._entries_by_user_tier.pop(user_id, None)
