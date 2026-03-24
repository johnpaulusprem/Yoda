"""
Memory consolidation engine for the Agentic AI Component Library.

Provides strategies for consolidating (summarizing, merging, extracting,
hierarchically organizing) memory entries to reduce volume while
preserving essential information.

Example:
    ```python
    from yoda_foundation.memory.consolidation import (
        ConsolidationEngine,
        EmbeddingClient,
        LLMClient,
    )

    engine = ConsolidationEngine(
        embedding_client=my_embedder,
        llm_client=my_llm,
    )
    result = await engine.consolidate(
        entries, ConsolidationStrategy.SUMMARIZE, security_context,
    )
    ```
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from yoda_foundation.exceptions.memory import MemoryConsolidationError
from yoda_foundation.memory.schemas import (
    ConsolidationResult,
    ConsolidationStrategy,
    MemoryContent,
    MemoryEntry,
)
from yoda_foundation.security.context import SecurityContext


@runtime_checkable
class EmbeddingClient(Protocol):
    """
    Protocol for embedding client used by the consolidation engine.

    Implementations must provide an async embed method that converts
    text into a vector representation.

    Example:
        ```python
        class MyEmbedder:
            async def embed(self, text: str) -> list[float]:
                return await my_model.encode(text)
        ```
    """

    async def embed(self, text: str) -> list[float]:
        """
        Generate an embedding vector for the given text.

        Args:
            text: Input text to embed.

        Returns:
            Embedding vector as a list of floats.
        """
        ...


@runtime_checkable
class LLMClient(Protocol):
    """
    Protocol for LLM client used by the consolidation engine.

    Implementations must provide an async complete method that generates
    text completions.

    Example:
        ```python
        class MyLLM:
            async def complete(self, prompt: str) -> str:
                return await my_model.generate(prompt)
        ```
    """

    async def complete(self, prompt: str) -> str:
        """
        Generate a text completion for the given prompt.

        Args:
            prompt: Input prompt for the LLM.

        Returns:
            Generated text completion.
        """
        ...


class ConsolidationEngine:
    """
    Engine for consolidating memory entries using various strategies.

    Supports summarization, merging, extraction, and hierarchical
    consolidation. When LLM and embedding clients are available, uses
    them for intelligent consolidation. Falls back to simple string
    concatenation when clients are not available.

    Attributes:
        embedding_client: Optional embedding client for vector operations.
        llm_client: Optional LLM client for text generation.

    Example:
        ```python
        engine = ConsolidationEngine(llm_client=my_llm)
        result = await engine.consolidate(
            entries=entries,
            strategy=ConsolidationStrategy.SUMMARIZE,
            security_context=security_context,
        )
        print(f"Reduced {result.original_count} -> {result.consolidated_count}")
        ```

    Raises:
        MemoryConsolidationError: When consolidation fails.
    """

    def __init__(
        self,
        embedding_client: EmbeddingClient | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        """
        Initialize the consolidation engine.

        Args:
            embedding_client: Optional embedding client for computing embeddings.
            llm_client: Optional LLM client for summarization and extraction.

        Example:
            ```python
            engine = ConsolidationEngine(
                embedding_client=my_embedder,
                llm_client=my_llm,
            )
            ```
        """
        self.embedding_client = embedding_client
        self.llm_client = llm_client

    async def consolidate(
        self,
        entries: list[MemoryEntry],
        strategy: ConsolidationStrategy,
        security_context: SecurityContext,
    ) -> ConsolidationResult:
        """
        Consolidate memory entries using the specified strategy.

        Args:
            entries: List of memory entries to consolidate.
            strategy: Consolidation strategy to apply.
            security_context: Security context for the operation.

        Returns:
            ConsolidationResult with the consolidated entries.

        Raises:
            MemoryConsolidationError: If consolidation fails.

        Example:
            ```python
            result = await engine.consolidate(
                entries, ConsolidationStrategy.MERGE, security_context,
            )
            ```
        """
        if not entries:
            return ConsolidationResult(
                original_count=0,
                consolidated_count=0,
                strategy=strategy,
                entries=[],
                duration_ms=0,
            )

        start_ms = int(time.monotonic() * 1000)

        try:
            strategy_map = {
                ConsolidationStrategy.SUMMARIZE: self._summarize,
                ConsolidationStrategy.MERGE: self._merge,
                ConsolidationStrategy.EXTRACT: self._extract,
                ConsolidationStrategy.HIERARCHICAL: self._hierarchical,
            }

            handler = strategy_map.get(strategy)
            if handler is None:
                raise MemoryConsolidationError(
                    message=f"Unknown consolidation strategy: {strategy.value}",
                    strategy=strategy.value,
                    entries_count=len(entries),
                )

            consolidated = await handler(entries)

            elapsed_ms = int(time.monotonic() * 1000) - start_ms
            return ConsolidationResult(
                original_count=len(entries),
                consolidated_count=len(consolidated),
                strategy=strategy,
                entries=consolidated,
                duration_ms=elapsed_ms,
            )
        except MemoryConsolidationError:
            raise
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            raise MemoryConsolidationError(
                message=f"Consolidation failed with strategy '{strategy.value}': {e}",
                strategy=strategy.value,
                entries_count=len(entries),
                cause=e,
            ) from e

    async def _summarize(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """
        Summarize entries into a single consolidated entry using LLM.

        Falls back to simple concatenation when LLM client is not available.

        Args:
            entries: Entries to summarize.

        Returns:
            List containing a single summarized entry.
        """
        combined_text = "\n\n".join(f"[{entry.id}] {entry.content.content}" for entry in entries)

        if self.llm_client is not None:
            prompt = (
                "Summarize the following memory entries into a concise, "
                "comprehensive summary that preserves key information:\n\n"
                f"{combined_text}\n\nSummary:"
            )
            summary = await self.llm_client.complete(prompt)
        else:
            # Simple fallback: take first 500 chars of combined text
            summary = combined_text[:500]
            if len(combined_text) > 500:
                summary += "..."

        # Compute embedding for the summary if client is available
        embedding: list[float] | None = None
        if self.embedding_client is not None:
            embedding = await self.embedding_client.embed(summary)

        # Aggregate metadata
        all_tags: list[str] = []
        for entry in entries:
            for tag in entry.tags:
                if tag not in all_tags:
                    all_tags.append(tag)

        avg_importance = sum(e.importance for e in entries) / len(entries)
        total_tokens = sum(e.content.token_count for e in entries)

        # Determine tier and scope from most common values
        tier = entries[0].tier
        scope = entries[0].scope

        consolidated_entry = MemoryEntry(
            id=f"mem_{uuid.uuid4().hex[:12]}",
            tier=tier,
            scope=scope,
            content=MemoryContent(
                content=summary,
                content_type="text",
                embedding=embedding,
                metadata={
                    "consolidated_from": [e.id for e in entries],
                    "strategy": "summarize",
                },
                token_count=total_tokens,
            ),
            importance=min(1.0, avg_importance + 0.1),
            access_count=0,
            created_at=datetime.now(UTC),
            tags=all_tags,
            metadata={
                "consolidation_strategy": "summarize",
                "source_count": len(entries),
            },
        )

        return [consolidated_entry]

    async def _merge(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """
        Merge similar entries together.

        Groups entries by overlapping tags and combines content from
        entries in each group. Falls back to content concatenation
        when LLM is unavailable.

        Args:
            entries: Entries to merge.

        Returns:
            List of merged entries (one per group).
        """
        # Group by tag similarity
        groups: list[list[MemoryEntry]] = []
        assigned: set[str] = set()

        for entry in entries:
            if entry.id in assigned:
                continue

            group = [entry]
            assigned.add(entry.id)

            entry_tags = set(entry.tags)
            for other in entries:
                if other.id in assigned:
                    continue
                other_tags = set(other.tags)
                # Merge if they share at least one tag
                if entry_tags & other_tags:
                    group.append(other)
                    assigned.add(other.id)

            groups.append(group)

        # Merge each group
        merged_entries: list[MemoryEntry] = []
        for group in groups:
            if len(group) == 1:
                merged_entries.append(group[0])
                continue

            combined_text = "\n---\n".join(e.content.content for e in group)

            if self.llm_client is not None:
                prompt = (
                    "Merge the following related memory entries into a single "
                    "coherent entry:\n\n"
                    f"{combined_text}\n\nMerged entry:"
                )
                merged_content = await self.llm_client.complete(prompt)
            else:
                merged_content = combined_text

            # Collect all tags
            all_tags: list[str] = []
            for entry in group:
                for tag in entry.tags:
                    if tag not in all_tags:
                        all_tags.append(tag)

            embedding: list[float] | None = None
            if self.embedding_client is not None:
                embedding = await self.embedding_client.embed(merged_content)

            total_tokens = sum(e.content.token_count for e in group)

            merged_entry = MemoryEntry(
                id=f"mem_{uuid.uuid4().hex[:12]}",
                tier=group[0].tier,
                scope=group[0].scope,
                content=MemoryContent(
                    content=merged_content,
                    content_type="text",
                    embedding=embedding,
                    metadata={
                        "consolidated_from": [e.id for e in group],
                        "strategy": "merge",
                    },
                    token_count=total_tokens,
                ),
                importance=min(1.0, max(e.importance for e in group)),
                access_count=sum(e.access_count for e in group),
                created_at=datetime.now(UTC),
                tags=all_tags,
                metadata={
                    "consolidation_strategy": "merge",
                    "source_count": len(group),
                },
            )
            merged_entries.append(merged_entry)

        return merged_entries

    async def _extract(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """
        Extract key facts from entries into distinct fact entries.

        Uses LLM to extract discrete facts. Falls back to splitting
        content by sentences.

        Args:
            entries: Entries to extract facts from.

        Returns:
            List of entries, each containing an extracted fact.
        """
        combined_text = "\n\n".join(e.content.content for e in entries)

        if self.llm_client is not None:
            prompt = (
                "Extract the key facts from the following memory entries. "
                "Return each fact on a separate line, prefixed with '- ':\n\n"
                f"{combined_text}\n\nKey facts:"
            )
            facts_text = await self.llm_client.complete(prompt)
            facts = [
                line.strip().lstrip("- ").strip()
                for line in facts_text.strip().split("\n")
                if line.strip() and line.strip() != "-"
            ]
        else:
            # Simple fallback: split by sentences
            sentences = combined_text.replace(".", ".\n").split("\n")
            facts = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 10]

        if not facts:
            facts = [combined_text[:200]]

        # Collect all tags from source entries
        all_tags: list[str] = []
        for entry in entries:
            for tag in entry.tags:
                if tag not in all_tags:
                    all_tags.append(tag)

        avg_importance = sum(e.importance for e in entries) / len(entries)

        # Determine tier and scope
        tier = entries[0].tier
        scope = entries[0].scope

        extracted_entries: list[MemoryEntry] = []
        for fact in facts:
            embedding: list[float] | None = None
            if self.embedding_client is not None:
                embedding = await self.embedding_client.embed(fact)

            extracted_entry = MemoryEntry(
                id=f"mem_{uuid.uuid4().hex[:12]}",
                tier=tier,
                scope=scope,
                content=MemoryContent(
                    content=fact,
                    content_type="text",
                    embedding=embedding,
                    metadata={
                        "consolidated_from": [e.id for e in entries],
                        "strategy": "extract",
                    },
                    token_count=len(fact.split()),
                ),
                importance=avg_importance,
                access_count=0,
                created_at=datetime.now(UTC),
                tags=all_tags,
                metadata={
                    "consolidation_strategy": "extract",
                    "source_count": len(entries),
                },
            )
            extracted_entries.append(extracted_entry)

        return extracted_entries

    async def _hierarchical(self, entries: list[MemoryEntry]) -> list[MemoryEntry]:
        """
        Apply multi-level hierarchical consolidation.

        First groups entries by tags/topics, then summarizes each group,
        and finally creates a top-level summary linking all groups.

        Args:
            entries: Entries to consolidate hierarchically.

        Returns:
            List of entries representing the hierarchical consolidation
            (group summaries plus a top-level overview).
        """
        # Step 1: Group by tags
        groups: dict[str, list[MemoryEntry]] = {}
        ungrouped: list[MemoryEntry] = []

        for entry in entries:
            if entry.tags:
                primary_tag = entry.tags[0]
                if primary_tag not in groups:
                    groups[primary_tag] = []
                groups[primary_tag].append(entry)
            else:
                ungrouped.append(entry)

        if ungrouped:
            groups["_ungrouped"] = ungrouped

        # Step 2: Summarize each group
        group_summaries: list[MemoryEntry] = []
        for group_tag, group_entries in groups.items():
            summarized = await self._summarize(group_entries)
            for summary_entry in summarized:
                summary_entry.metadata["hierarchy_level"] = "group"
                summary_entry.metadata["group_tag"] = group_tag
                group_summaries.append(summary_entry)

        # Step 3: Create a top-level overview if multiple groups
        if len(group_summaries) > 1:
            overview_entries = await self._summarize(group_summaries)
            for overview in overview_entries:
                overview.metadata["hierarchy_level"] = "overview"
                overview.importance = min(1.0, overview.importance + 0.2)
            return overview_entries + group_summaries

        return group_summaries
