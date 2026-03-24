"""
Memory-to-knowledge-graph linker for bidirectional linking.

Creates and manages bidirectional links between memory entries and
knowledge graph entities, enabling traversal from memories to their
associated entities and vice versa.

Example:
    ```python
    from yoda_foundation.memory.graph_memory.memory_linker import (
        MemoryKGLink,
        MemoryKGLinker,
    )

    linker = MemoryKGLinker()

    link = await linker.link_memory_to_entity(
        memory_id="mem_abc123",
        entity_id="ent_xyz789",
        link_type="mentions",
        security_context=context,
    )

    related = await linker.get_related_memories(
        entity_id="ent_xyz789",
        security_context=context,
    )
    print(f"Found {len(related)} related memories")
    ```
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from yoda_foundation.exceptions.memory import MemoryError
from yoda_foundation.security.context import SecurityContext


@dataclass(frozen=True)
class MemoryKGLink:
    """
    Bidirectional link between a memory entry and a knowledge graph entity.

    Attributes:
        link_id: Unique identifier for this link.
        memory_id: Identifier of the linked memory entry.
        entity_id: Identifier of the linked knowledge graph entity.
        link_type: Semantic type of the link (e.g., ``"mentions"``,
            ``"derived_from"``, ``"supports"``).
        created_at: Timestamp when the link was created.
        metadata: Additional link metadata.

    Example:
        ```python
        link = MemoryKGLink(
            link_id="link_abc123",
            memory_id="mem_001",
            entity_id="ent_002",
            link_type="mentions",
            created_at=datetime.now(UTC),
            metadata={"confidence": 0.95},
        )
        ```
    """

    link_id: str
    memory_id: str
    entity_id: str
    link_type: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryKGLinker:
    """
    Manages bidirectional links between memory entries and KG entities.

    Stores links in an in-memory dictionary, indexed by both memory ID
    and entity ID for efficient bidirectional lookups.

    Example:
        ```python
        linker = MemoryKGLinker()

        # Create a link
        link = await linker.link_memory_to_entity(
            memory_id="mem_abc",
            entity_id="ent_xyz",
            link_type="mentions",
            security_context=ctx,
        )

        # Find related memories for an entity
        memories = await linker.get_related_memories(
            entity_id="ent_xyz",
            security_context=ctx,
        )

        # Find entity context for a memory
        entities = await linker.get_entity_context(
            memory_id="mem_abc",
            security_context=ctx,
        )

        # Remove a link
        removed = await linker.unlink(
            memory_id="mem_abc",
            entity_id="ent_xyz",
            security_context=ctx,
        )
        ```

    Raises:
        MemoryError: When link operations fail.
        MemoryNotFoundError: When queried link does not exist.
    """

    def __init__(self) -> None:
        """
        Initialise the memory-KG linker with empty indices.

        Example:
            ```python
            linker = MemoryKGLinker()
            ```
        """
        # Primary storage: link_id -> MemoryKGLink
        self._links: dict[str, MemoryKGLink] = {}
        # Index: memory_id -> set of link_ids
        self._memory_index: dict[str, set[str]] = defaultdict(set)
        # Index: entity_id -> set of link_ids
        self._entity_index: dict[str, set[str]] = defaultdict(set)

    async def link_memory_to_entity(
        self,
        memory_id: str,
        entity_id: str,
        link_type: str,
        security_context: SecurityContext,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryKGLink:
        """
        Create a bidirectional link between a memory entry and a KG entity.

        If a link with the same memory_id, entity_id, and link_type already
        exists, a new link is still created (allowing multiple link instances
        with different metadata).

        Args:
            memory_id: Identifier of the memory entry.
            entity_id: Identifier of the knowledge graph entity.
            link_type: Semantic label for the link relationship.
            security_context: Security context for authorisation.
            metadata: Optional additional metadata for the link.

        Returns:
            The newly created ``MemoryKGLink``.

        Raises:
            MemoryError: If link creation fails due to invalid parameters.

        Example:
            ```python
            link = await linker.link_memory_to_entity(
                memory_id="mem_001",
                entity_id="ent_002",
                link_type="derived_from",
                security_context=ctx,
                metadata={"confidence": 0.9},
            )
            print(f"Created link: {link.link_id}")
            ```
        """
        security_context.require_permission("memory.write")

        if not memory_id or not memory_id.strip():
            raise MemoryError(
                message="memory_id must be a non-empty string",
                operation="link",
            )
        if not entity_id or not entity_id.strip():
            raise MemoryError(
                message="entity_id must be a non-empty string",
                operation="link",
            )
        if not link_type or not link_type.strip():
            raise MemoryError(
                message="link_type must be a non-empty string",
                operation="link",
            )

        link_id = f"link_{uuid.uuid4().hex[:12]}"

        link = MemoryKGLink(
            link_id=link_id,
            memory_id=memory_id,
            entity_id=entity_id,
            link_type=link_type,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
        )

        self._links[link_id] = link
        self._memory_index[memory_id].add(link_id)
        self._entity_index[entity_id].add(link_id)

        return link

    async def get_related_memories(
        self,
        entity_id: str,
        security_context: SecurityContext,
        *,
        max_results: int = 10,
    ) -> list[str]:
        """
        Retrieve memory IDs linked to a given knowledge graph entity.

        Returns the most recently linked memories first, limited to
        ``max_results``.

        Args:
            entity_id: Identifier of the knowledge graph entity.
            security_context: Security context for authorisation.
            max_results: Maximum number of memory IDs to return.

        Returns:
            List of memory IDs linked to the entity, ordered by link
            creation time (most recent first).

        Example:
            ```python
            memory_ids = await linker.get_related_memories(
                entity_id="ent_xyz",
                security_context=ctx,
                max_results=5,
            )
            for mid in memory_ids:
                print(f"Related memory: {mid}")
            ```
        """
        security_context.require_permission("memory.read")

        link_ids = self._entity_index.get(entity_id, set())
        if not link_ids:
            return []

        # Collect links, sort by creation time (newest first)
        links = [self._links[lid] for lid in link_ids if lid in self._links]
        links.sort(key=lambda lnk: lnk.created_at, reverse=True)

        # Deduplicate memory IDs while preserving order
        seen: set[str] = set()
        result: list[str] = []
        for link in links:
            if link.memory_id not in seen:
                seen.add(link.memory_id)
                result.append(link.memory_id)
                if len(result) >= max_results:
                    break

        return result

    async def get_entity_context(
        self,
        memory_id: str,
        security_context: SecurityContext,
    ) -> list[str]:
        """
        Retrieve entity IDs linked to a given memory entry.

        Args:
            memory_id: Identifier of the memory entry.
            security_context: Security context for authorisation.

        Returns:
            List of entity IDs linked to the memory entry.

        Example:
            ```python
            entity_ids = await linker.get_entity_context(
                memory_id="mem_abc",
                security_context=ctx,
            )
            for eid in entity_ids:
                print(f"Related entity: {eid}")
            ```
        """
        security_context.require_permission("memory.read")

        link_ids = self._memory_index.get(memory_id, set())
        if not link_ids:
            return []

        # Collect links, sort by creation time (newest first)
        links = [self._links[lid] for lid in link_ids if lid in self._links]
        links.sort(key=lambda lnk: lnk.created_at, reverse=True)

        # Deduplicate entity IDs while preserving order
        seen: set[str] = set()
        result: list[str] = []
        for link in links:
            if link.entity_id not in seen:
                seen.add(link.entity_id)
                result.append(link.entity_id)

        return result

    async def unlink(
        self,
        memory_id: str,
        entity_id: str,
        security_context: SecurityContext,
    ) -> bool:
        """
        Remove all links between a specific memory entry and KG entity.

        Args:
            memory_id: Identifier of the memory entry.
            entity_id: Identifier of the knowledge graph entity.
            security_context: Security context for authorisation.

        Returns:
            ``True`` if at least one link was removed, ``False`` if no
            matching link existed.

        Example:
            ```python
            removed = await linker.unlink(
                memory_id="mem_abc",
                entity_id="ent_xyz",
                security_context=ctx,
            )
            if removed:
                print("Link removed successfully")
            ```
        """
        security_context.require_permission("memory.write")

        # Find all links matching both memory_id and entity_id
        memory_links = self._memory_index.get(memory_id, set())
        entity_links = self._entity_index.get(entity_id, set())
        matching_link_ids = memory_links & entity_links

        if not matching_link_ids:
            return False

        for link_id in matching_link_ids:
            # Remove from primary storage
            self._links.pop(link_id, None)
            # Remove from indices
            self._memory_index[memory_id].discard(link_id)
            self._entity_index[entity_id].discard(link_id)

        # Clean up empty index entries
        if not self._memory_index.get(memory_id):
            self._memory_index.pop(memory_id, None)
        if not self._entity_index.get(entity_id):
            self._entity_index.pop(entity_id, None)

        return True

    async def get_link_count(
        self,
        security_context: SecurityContext,
    ) -> int:
        """
        Return the total number of stored links.

        Args:
            security_context: Security context for authorisation.

        Returns:
            Total link count.

        Example:
            ```python
            count = await linker.get_link_count(security_context=ctx)
            print(f"Total links: {count}")
            ```
        """
        security_context.require_permission("memory.read")

        return len(self._links)

    async def get_links_for_memory(
        self,
        memory_id: str,
        security_context: SecurityContext,
    ) -> list[MemoryKGLink]:
        """
        Retrieve all link objects for a given memory entry.

        Args:
            memory_id: Identifier of the memory entry.
            security_context: Security context for authorisation.

        Returns:
            List of ``MemoryKGLink`` objects, sorted by creation time
            (newest first).

        Example:
            ```python
            links = await linker.get_links_for_memory(
                memory_id="mem_abc",
                security_context=ctx,
            )
            for link in links:
                print(f"{link.link_type} -> {link.entity_id}")
            ```
        """
        security_context.require_permission("memory.read")

        link_ids = self._memory_index.get(memory_id, set())
        links = [self._links[lid] for lid in link_ids if lid in self._links]
        links.sort(key=lambda lnk: lnk.created_at, reverse=True)
        return links
