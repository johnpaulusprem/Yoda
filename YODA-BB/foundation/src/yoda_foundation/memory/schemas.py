"""
Memory schemas and data structures for the Agentic AI Component Library.

This module provides the core data structures used across all memory tiers
including enums for classification, dataclasses for entries, search filters,
and result types.

Example:
    ```python
    from yoda_foundation.memory.schemas import (
        MemoryTier,
        MemoryScope,
        MemoryContent,
        MemoryEntry,
        SearchFilter,
    )

    content = MemoryContent(content="User likes concise answers")
    entry = MemoryEntry.create(
        tier=MemoryTier.SEMANTIC,
        scope=MemoryScope.USER,
        content=content,
        importance=0.8,
        tags=["preference"],
    )
    ```
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class MemoryTier(Enum):
    """
    Classification of memory tiers in the multi-tier memory system.

    Each tier serves a different purpose:
    - WORKING: Short-lived active task context, auto-expires
    - EPISODIC: Event/episode based memories, time-ordered
    - SEMANTIC: Knowledge-based memories with vector similarity
    - PROCEDURAL: Skill/procedure storage with pattern matching

    Example:
        ```python
        tier = MemoryTier.WORKING
        assert tier.value == "working"
        ```
    """

    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryScope(Enum):
    """
    Scope of memory visibility and access.

    Scopes control who can access memory entries:
    - SESSION: Limited to current session
    - USER: Visible to the owning user across sessions
    - TENANT: Visible to all users in a tenant
    - GLOBAL: Visible to all users

    Example:
        ```python
        scope = MemoryScope.USER
        assert scope.value == "user"
        ```
    """

    SESSION = "session"
    USER = "user"
    TENANT = "tenant"
    GLOBAL = "global"


class ContextStrategy(Enum):
    """
    Strategy for building context from memory entries.

    - RECENCY: Prioritize most recently created/accessed entries
    - RELEVANCE: Prioritize entries most relevant to the query
    - IMPORTANCE: Prioritize entries with highest importance scores
    - HYBRID: Weighted combination of recency, relevance, and importance

    Example:
        ```python
        strategy = ContextStrategy.HYBRID
        assert strategy.value == "hybrid"
        ```
    """

    RECENCY = "recency"
    RELEVANCE = "relevance"
    IMPORTANCE = "importance"
    HYBRID = "hybrid"


class ConsolidationStrategy(Enum):
    """
    Strategy for consolidating memory entries.

    - SUMMARIZE: Use LLM to summarize groups of entries
    - MERGE: Combine similar entries into single entries
    - EXTRACT: Extract key facts from entries
    - HIERARCHICAL: Multi-level consolidation with progressive summarization

    Example:
        ```python
        strategy = ConsolidationStrategy.SUMMARIZE
        assert strategy.value == "summarize"
        ```
    """

    SUMMARIZE = "summarize"
    MERGE = "merge"
    EXTRACT = "extract"
    HIERARCHICAL = "hierarchical"


@dataclass
class MemoryContent:
    """
    Content payload for a memory entry.

    Encapsulates the actual content along with its type, optional embedding
    vector, metadata, and token count for budget management.

    Attributes:
        content: The textual content of the memory
        content_type: MIME-like type descriptor (e.g., "text", "code", "json")
        embedding: Optional pre-computed embedding vector
        metadata: Additional content-level metadata
        token_count: Approximate token count for budget tracking

    Example:
        ```python
        content = MemoryContent(
            content="The user prefers Python over JavaScript.",
            content_type="text",
            metadata={"source": "conversation"},
            token_count=8,
        )
        ```
    """

    content: str
    content_type: str = "text"
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    token_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """
        Convert content to dictionary.

        Returns:
            Dictionary representation of the content.

        Example:
            ```python
            content_dict = content.to_dict()
            ```
        """
        return {
            "content": self.content,
            "content_type": self.content_type,
            "embedding": self.embedding,
            "metadata": self.metadata,
            "token_count": self.token_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryContent:
        """
        Create MemoryContent from dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            MemoryContent instance.

        Example:
            ```python
            content = MemoryContent.from_dict({"content": "hello", "content_type": "text"})
            ```
        """
        return cls(
            content=data["content"],
            content_type=data.get("content_type", "text"),
            embedding=data.get("embedding"),
            metadata=data.get("metadata", {}),
            token_count=data.get("token_count", 0),
        )


@dataclass
class MemoryEntry:
    """
    A single entry in the multi-tier memory system.

    Represents a unit of memory with content, tier classification, scope,
    importance scoring, access tracking, and lifecycle management.

    Attributes:
        id: Unique entry identifier
        tier: Which memory tier this entry belongs to
        scope: Visibility scope of the entry
        content: The memory content payload
        importance: Importance score from 0.0 (least) to 1.0 (most)
        access_count: Number of times this entry has been accessed
        created_at: When the entry was created
        last_accessed: When the entry was last accessed
        expires_at: Optional expiration timestamp
        tags: Classification tags for filtering
        metadata: Additional entry-level metadata

    Example:
        ```python
        entry = MemoryEntry.create(
            tier=MemoryTier.EPISODIC,
            scope=MemoryScope.USER,
            content=MemoryContent(content="Completed data analysis task"),
            importance=0.7,
            tags=["task", "completed"],
        )
        ```
    """

    id: str
    tier: MemoryTier
    scope: MemoryScope
    content: MemoryContent
    importance: float = 0.5
    access_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime | None = None
    expires_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        tier: MemoryTier,
        scope: MemoryScope,
        content: MemoryContent,
        importance: float = 0.5,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        entry_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryEntry:
        """
        Factory method to create a new memory entry with auto-generated ID.

        Args:
            tier: Memory tier classification.
            scope: Visibility scope.
            content: Memory content payload.
            importance: Importance score (0.0-1.0).
            tags: Optional classification tags.
            metadata: Optional additional metadata.
            entry_id: Optional custom ID (auto-generated if not provided).
            expires_at: Optional expiration timestamp.

        Returns:
            New MemoryEntry instance.

        Example:
            ```python
            entry = MemoryEntry.create(
                tier=MemoryTier.WORKING,
                scope=MemoryScope.SESSION,
                content=MemoryContent(content="Current task context"),
                importance=0.9,
                tags=["active"],
            )
            ```
        """
        now = datetime.now(UTC)
        return cls(
            id=entry_id or f"mem_{uuid.uuid4().hex[:12]}",
            tier=tier,
            scope=scope,
            content=content,
            importance=max(0.0, min(1.0, importance)),
            access_count=0,
            created_at=now,
            last_accessed=None,
            expires_at=expires_at,
            tags=tags or [],
            metadata=metadata or {},
        )

    def mark_accessed(self) -> None:
        """
        Mark the entry as accessed, updating count and timestamp.

        Example:
            ```python
            entry.mark_accessed()
            assert entry.access_count >= 1
            assert entry.last_accessed is not None
            ```
        """
        self.access_count += 1
        self.last_accessed = datetime.now(UTC)

    def is_expired(self) -> bool:
        """
        Check if the entry has passed its expiration time.

        Returns:
            True if the entry has expired, False otherwise.

        Example:
            ```python
            if entry.is_expired():
                await tier.delete(entry.id, security_context)
            ```
        """
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """
        Convert entry to a serializable dictionary.

        Returns:
            Dictionary representation of the entry.

        Example:
            ```python
            entry_dict = entry.to_dict()
            json_str = json.dumps(entry_dict)
            ```
        """
        return {
            "id": self.id,
            "tier": self.tier.value,
            "scope": self.scope.value,
            "content": self.content.to_dict(),
            "importance": self.importance,
            "access_count": self.access_count,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        """
        Create a MemoryEntry from a dictionary.

        Args:
            data: Dictionary representation of a MemoryEntry.

        Returns:
            MemoryEntry instance.

        Example:
            ```python
            entry = MemoryEntry.from_dict(entry_dict)
            assert entry.id == entry_dict["id"]
            ```
        """
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        last_accessed = data.get("last_accessed")
        if isinstance(last_accessed, str):
            last_accessed = datetime.fromisoformat(last_accessed)

        expires_at = data.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)

        return cls(
            id=data["id"],
            tier=MemoryTier(data["tier"]),
            scope=MemoryScope(data["scope"]),
            content=MemoryContent.from_dict(data["content"]),
            importance=data.get("importance", 0.5),
            access_count=data.get("access_count", 0),
            created_at=created_at,
            last_accessed=last_accessed,
            expires_at=expires_at,
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SearchFilter:
    """
    Filter criteria for searching memory entries.

    All filter fields are optional; None means no constraint on that field.

    Attributes:
        tiers: Filter by specific memory tiers
        scopes: Filter by specific scopes
        tags: Filter by tags (entries must have at least one matching tag)
        min_importance: Minimum importance score threshold
        since: Only entries created after this timestamp
        until: Only entries created before this timestamp
        content_type: Filter by content type
        limit: Maximum number of results to return

    Example:
        ```python
        filters = SearchFilter(
            tiers=[MemoryTier.SEMANTIC, MemoryTier.EPISODIC],
            min_importance=0.5,
            limit=20,
        )
        ```
    """

    tiers: list[MemoryTier] | None = None
    scopes: list[MemoryScope] | None = None
    tags: list[str] | None = None
    min_importance: float | None = None
    since: datetime | None = None
    until: datetime | None = None
    content_type: str | None = None
    limit: int = 10


@dataclass
class SearchResult:
    """
    Result of a memory search operation.

    Attributes:
        entries: List of matching memory entries
        scores: Relevance scores corresponding to each entry
        total_count: Total number of matching entries (before limit)
        query_time_ms: Time taken for the search in milliseconds

    Example:
        ```python
        result = await tier.search("user preferences", filters, security_context)
        for entry, score in zip(result.entries, result.scores):
            print(f"{entry.id}: {score:.2f}")
        ```
    """

    entries: list[MemoryEntry] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    total_count: int = 0
    query_time_ms: int = 0


@dataclass
class StoreResult:
    """
    Result of a memory store operation.

    Attributes:
        entry_id: ID of the stored entry
        tier: Tier the entry was stored in
        stored: Whether the store succeeded
        message: Optional status message

    Example:
        ```python
        result = await tier.store(entry, security_context)
        if result.stored:
            print(f"Stored as {result.entry_id} in {result.tier.value}")
        ```
    """

    entry_id: str
    tier: MemoryTier
    stored: bool
    message: str = ""


@dataclass
class ConsolidationResult:
    """
    Result of a memory consolidation operation.

    Attributes:
        original_count: Number of entries before consolidation
        consolidated_count: Number of entries after consolidation
        strategy: The strategy used for consolidation
        entries: The consolidated entries
        duration_ms: Time taken for consolidation in milliseconds

    Example:
        ```python
        result = await engine.consolidate(entries, strategy, security_context)
        print(f"Reduced {result.original_count} -> {result.consolidated_count}")
        ```
    """

    original_count: int
    consolidated_count: int
    strategy: ConsolidationStrategy
    entries: list[MemoryEntry] = field(default_factory=list)
    duration_ms: int = 0


@dataclass
class ContextResult:
    """
    Result of building a context from memory entries.

    Attributes:
        entries: Selected memory entries for context
        strategy: The strategy used for context selection
        total_tokens: Total token count of selected entries
        relevance_scores: Relevance scores for each selected entry

    Example:
        ```python
        result = await builder.build("What is the task?", entries, security_context)
        for entry, score in zip(result.entries, result.relevance_scores):
            print(f"{entry.content.content[:50]}: {score:.2f}")
        ```
    """

    entries: list[MemoryEntry] = field(default_factory=list)
    strategy: ContextStrategy = ContextStrategy.HYBRID
    total_tokens: int = 0
    relevance_scores: list[float] = field(default_factory=list)


@dataclass
class MemoryStats:
    """
    Statistics about the memory system state.

    Attributes:
        total_entries: Total number of entries across all tiers
        entries_by_tier: Count of entries per tier
        entries_by_scope: Count of entries per scope
        total_tokens: Total token count across all entries
        oldest_entry: Timestamp of the oldest entry
        newest_entry: Timestamp of the newest entry

    Example:
        ```python
        stats = await manager.get_stats(security_context)
        print(f"Total entries: {stats.total_entries}")
        for tier, count in stats.entries_by_tier.items():
            print(f"  {tier.value}: {count}")
        ```
    """

    total_entries: int = 0
    entries_by_tier: dict[MemoryTier, int] = field(default_factory=dict)
    entries_by_scope: dict[MemoryScope, int] = field(default_factory=dict)
    total_tokens: int = 0
    oldest_entry: datetime | None = None
    newest_entry: datetime | None = None
