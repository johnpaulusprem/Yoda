"""
Conversation memory extraction for Mem0-style graph memory.

Extracts entities and relations from conversation turns using an LLM,
detects contradictions against existing facts, and resolves coreferences
between newly extracted entities and previously known ones.

Example:
    ```python
    from yoda_foundation.memory.graph_memory.conversation_extractor import (
        ConversationMemoryExtractor,
        ConversationMemoryUpdate,
        Contradiction,
    )
    from yoda_foundation.memory.consolidation import LLMClient

    class MyLLM:
        async def complete(self, prompt: str) -> str:
            return await call_model(prompt)

    extractor = ConversationMemoryExtractor(llm_client=MyLLM())
    update = await extractor.extract_from_turn(
        user_message="My name is Alice and I work at Acme Corp.",
        assistant_message="Nice to meet you, Alice!",
        conversation_id="conv_001",
        security_context=context,
    )

    for entity in update.new_entities:
        print(f"Discovered: {entity['name']} ({entity['type']})")
    ```
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from yoda_foundation.exceptions.memory import (
    MemoryConsolidationError,
    MemoryContextError,
)
from yoda_foundation.memory.consolidation import LLMClient
from yoda_foundation.memory.schemas import (
    MemoryContent,
    MemoryEntry,
    MemoryScope,
    MemoryTier,
)
from yoda_foundation.security.context import SecurityContext


@dataclass(frozen=True)
class Contradiction:
    """
    Represents a contradiction between an existing fact and a new fact.

    Detected when a conversation turn produces information that conflicts
    with previously stored knowledge.

    Attributes:
        existing_fact: The previously known fact text.
        new_fact: The newly extracted contradictory fact text.
        conflict_type: Category of conflict (e.g., ``"attribute_change"``,
            ``"negation"``, ``"temporal_supersede"``).
        resolution: How the contradiction should be resolved (e.g.,
            ``"keep_new"``, ``"keep_existing"``, ``"flag_for_review"``).

    Example:
        ```python
        contradiction = Contradiction(
            existing_fact="Alice works at Acme Corp",
            new_fact="Alice works at Globex Inc",
            conflict_type="attribute_change",
            resolution="keep_new",
        )
        ```
    """

    existing_fact: str
    new_fact: str
    conflict_type: str
    resolution: str


@dataclass(frozen=True)
class ConversationMemoryUpdate:
    """
    Result of extracting memory-relevant information from a conversation turn.

    Contains newly discovered entities, updates to existing entities,
    new relations, memory entries to persist, and any detected contradictions.

    Attributes:
        new_entities: Newly discovered entities (dicts with name, type, attributes).
        updated_entities: Entities whose attributes were updated.
        new_relations: Newly discovered relations (dicts with subject, predicate, object).
        memory_entries: MemoryEntry objects ready for storage.
        contradictions: Contradictions detected against existing knowledge.

    Example:
        ```python
        update = await extractor.extract_from_turn(
            user_message="I moved from NYC to London.",
            assistant_message="Noted your location change.",
            conversation_id="conv_001",
            security_context=context,
        )
        print(f"New entities: {len(update.new_entities)}")
        print(f"Contradictions: {len(update.contradictions)}")
        ```
    """

    new_entities: tuple[dict[str, Any], ...] = ()
    updated_entities: tuple[dict[str, Any], ...] = ()
    new_relations: tuple[dict[str, Any], ...] = ()
    memory_entries: tuple[MemoryEntry, ...] = ()
    contradictions: tuple[Contradiction, ...] = ()


_EXTRACTION_PROMPT_TEMPLATE = """\
You are a knowledge extraction system. Analyse the following conversation turn \
and extract structured information.

## Conversation Turn
User: {user_message}
Assistant: {assistant_message}

## Instructions
Extract:
1. **Entities** - people, organisations, locations, concepts, products, or \
other named items mentioned. For each provide: name, type, and any attributes.
2. **Relations** - relationships between entities. For each provide: \
subject (entity name), predicate (relation label), object (entity name).

Respond ONLY with valid JSON in this exact format (no markdown fences):
{{
  "entities": [
    {{"name": "...", "type": "...", "attributes": {{}}}}
  ],
  "relations": [
    {{"subject": "...", "predicate": "...", "object": "..."}}
  ]
}}

If nothing can be extracted, return {{"entities": [], "relations": []}}.
"""

_CONTRADICTION_PROMPT_TEMPLATE = """\
You are a fact-checking system. Compare the NEW facts against the EXISTING \
facts and identify contradictions.

## Existing Facts
{existing_facts}

## New Facts
{new_facts}

## Instructions
For each contradiction found, provide:
- existing_fact: the original fact text
- new_fact: the contradicting new fact text
- conflict_type: one of "attribute_change", "negation", "temporal_supersede"
- resolution: one of "keep_new", "keep_existing", "flag_for_review"

Respond ONLY with valid JSON (no markdown fences):
{{
  "contradictions": [
    {{
      "existing_fact": "...",
      "new_fact": "...",
      "conflict_type": "...",
      "resolution": "..."
    }}
  ]
}}

If no contradictions, return {{"contradictions": []}}.
"""

_COREFERENCE_PROMPT_TEMPLATE = """\
You are a coreference resolution system. Determine which of the NEW entities \
are the same as EXISTING entities.

## Existing Entities
{existing_entities}

## New Entities
{new_entities}

## Instructions
For each new entity that matches an existing entity, provide:
- new_name: the name from the new entities list
- existing_name: the matching name from the existing entities list
- merged_attributes: combined attributes (prefer new values for conflicts)

Respond ONLY with valid JSON (no markdown fences):
{{
  "matches": [
    {{
      "new_name": "...",
      "existing_name": "...",
      "merged_attributes": {{}}
    }}
  ],
  "unmatched": [
    {{"name": "...", "type": "...", "attributes": {{}}}}
  ]
}}
"""

# Simple regex patterns for fallback extraction when no LLM is available.
_PROPER_NOUN_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")


class ConversationMemoryExtractor:
    """
    Extracts entities and relations from conversation turns.

    Uses an LLM to parse each conversation turn into structured entities
    and relations suitable for knowledge-graph storage. Falls back to
    simple regex-based proper-noun extraction when no LLM is available.

    Attributes:
        llm_client: Optional LLM client for intelligent extraction.

    Example:
        ```python
        extractor = ConversationMemoryExtractor(llm_client=my_llm)

        update = await extractor.extract_from_turn(
            user_message="I just started at Google.",
            assistant_message="Congrats on the new role!",
            conversation_id="conv_42",
            security_context=context,
        )

        for entity in update.new_entities:
            print(entity["name"], entity["type"])
        ```

    Raises:
        MemoryConsolidationError: When LLM extraction or parsing fails.
        MemoryContextError: When coreference resolution fails.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        """
        Initialise the conversation memory extractor.

        Args:
            llm_client: Optional LLM client conforming to the
                ``LLMClient`` protocol (async ``complete(prompt) -> str``).
                When ``None``, a simple regex fallback is used.

        Example:
            ```python
            extractor = ConversationMemoryExtractor(llm_client=my_llm)
            ```
        """
        self._llm_client = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract_from_turn(
        self,
        user_message: str,
        assistant_message: str,
        conversation_id: str,
        security_context: SecurityContext,
    ) -> ConversationMemoryUpdate:
        """
        Extract entities, relations, and memory entries from a conversation turn.

        Args:
            user_message: The user's message text.
            assistant_message: The assistant's response text.
            conversation_id: Unique identifier for the conversation.
            security_context: Security context for authorisation.

        Returns:
            A ``ConversationMemoryUpdate`` containing extracted entities,
            relations, memory entries, and any detected contradictions.

        Raises:
            MemoryConsolidationError: If extraction fails.

        Example:
            ```python
            update = await extractor.extract_from_turn(
                user_message="My dog's name is Max.",
                assistant_message="Cute name for a dog!",
                conversation_id="conv_01",
                security_context=ctx,
            )
            ```
        """
        security_context.require_permission("memory.write")

        if self._llm_client is not None:
            entities, relations = await self._extract_with_llm(user_message, assistant_message)
        else:
            entities, relations = await self._extract_with_regex(user_message, assistant_message)

        # Build memory entries from extracted information
        memory_entries = self._build_memory_entries(
            entities=entities,
            relations=relations,
            conversation_id=conversation_id,
            user_message=user_message,
            assistant_message=assistant_message,
            security_context=security_context,
        )

        return ConversationMemoryUpdate(
            new_entities=tuple(entities),
            updated_entities=(),
            new_relations=tuple(relations),
            memory_entries=tuple(memory_entries),
            contradictions=(),
        )

    async def detect_contradictions(
        self,
        new_facts: list[str],
        existing_facts: list[str],
        security_context: SecurityContext,
    ) -> list[Contradiction]:
        """
        Detect contradictions between new facts and existing knowledge.

        Args:
            new_facts: List of newly extracted fact strings.
            existing_facts: List of previously stored fact strings.
            security_context: Security context for authorisation.

        Returns:
            List of ``Contradiction`` instances describing each conflict.

        Raises:
            MemoryConsolidationError: If contradiction detection fails.

        Example:
            ```python
            contradictions = await extractor.detect_contradictions(
                new_facts=["Alice works at Globex"],
                existing_facts=["Alice works at Acme"],
                security_context=ctx,
            )
            for c in contradictions:
                print(f"{c.conflict_type}: {c.existing_fact} vs {c.new_fact}")
            ```
        """
        security_context.require_permission("memory.read")

        if not new_facts or not existing_facts:
            return []

        if self._llm_client is None:
            return self._detect_contradictions_simple(new_facts, existing_facts)

        prompt = _CONTRADICTION_PROMPT_TEMPLATE.format(
            existing_facts="\n".join(f"- {f}" for f in existing_facts),
            new_facts="\n".join(f"- {f}" for f in new_facts),
        )

        try:
            raw_response = await self._llm_client.complete(prompt)
            parsed = self._parse_json_response(raw_response)
        except (ValueError, TypeError, KeyError) as exc:
            raise MemoryConsolidationError(
                message=f"Contradiction detection LLM call failed: {exc}",
                strategy="contradiction_detection",
                cause=exc,
            ) from exc

        contradiction_dicts: list[dict[str, Any]] = parsed.get("contradictions", [])
        contradictions: list[Contradiction] = []
        for item in contradiction_dicts:
            contradictions.append(
                Contradiction(
                    existing_fact=str(item.get("existing_fact", "")),
                    new_fact=str(item.get("new_fact", "")),
                    conflict_type=str(item.get("conflict_type", "attribute_change")),
                    resolution=str(item.get("resolution", "flag_for_review")),
                )
            )
        return contradictions

    async def resolve_coreferences(
        self,
        entities: list[dict[str, Any]],
        existing_entities: list[dict[str, Any]],
        security_context: SecurityContext,
    ) -> list[dict[str, Any]]:
        """
        Resolve coreferences between new and existing entities.

        Merges entities that refer to the same real-world object, combining
        their attributes and preferring newer values on conflict.

        Args:
            entities: Newly extracted entity dicts (name, type, attributes).
            existing_entities: Previously known entity dicts.
            security_context: Security context for authorisation.

        Returns:
            Resolved list of entity dicts with coreferences merged.

        Raises:
            MemoryContextError: If coreference resolution fails.

        Example:
            ```python
            resolved = await extractor.resolve_coreferences(
                entities=[{"name": "Bob", "type": "person", "attributes": {}}],
                existing_entities=[
                    {"name": "Robert", "type": "person", "attributes": {"alias": "Bob"}}
                ],
                security_context=ctx,
            )
            ```
        """
        security_context.require_permission("memory.write")

        if not entities:
            return []

        if not existing_entities:
            return list(entities)

        if self._llm_client is None:
            return self._resolve_coreferences_simple(entities, existing_entities)

        prompt = _COREFERENCE_PROMPT_TEMPLATE.format(
            existing_entities=json.dumps(existing_entities, indent=2),
            new_entities=json.dumps(entities, indent=2),
        )

        try:
            raw_response = await self._llm_client.complete(prompt)
            parsed = self._parse_json_response(raw_response)
        except (ValueError, TypeError, KeyError) as exc:
            raise MemoryContextError(
                message=f"Coreference resolution LLM call failed: {exc}",
                strategy="coreference_resolution",
                cause=exc,
            ) from exc

        resolved: list[dict[str, Any]] = []

        # Add matched entities with merged attributes
        for match in parsed.get("matches", []):
            merged: dict[str, Any] = {
                "name": str(match.get("existing_name", match.get("new_name", ""))),
                "type": "entity",
                "attributes": match.get("merged_attributes", {}),
            }
            # Preserve type from existing if available
            for existing in existing_entities:
                if existing.get("name") == merged["name"]:
                    merged["type"] = existing.get("type", "entity")
                    break
            resolved.append(merged)

        # Add unmatched entities as-is
        for unmatched in parsed.get("unmatched", []):
            resolved.append(
                {
                    "name": str(unmatched.get("name", "")),
                    "type": str(unmatched.get("type", "entity")),
                    "attributes": unmatched.get("attributes", {}),
                }
            )

        return resolved

    # ------------------------------------------------------------------
    # LLM-based extraction
    # ------------------------------------------------------------------

    async def _extract_with_llm(
        self,
        user_message: str,
        assistant_message: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Extract entities and relations via LLM prompting.

        Args:
            user_message: User message text.
            assistant_message: Assistant response text.

        Returns:
            Tuple of (entities list, relations list).

        Raises:
            MemoryConsolidationError: If LLM call or parsing fails.
        """
        if self._llm_client is None:
            raise MemoryConsolidationError(
                message="LLM client is required for LLM-based extraction but was None",
                strategy="conversation_extraction",
            )

        prompt = _EXTRACTION_PROMPT_TEMPLATE.format(
            user_message=user_message,
            assistant_message=assistant_message,
        )

        try:
            raw_response = await self._llm_client.complete(prompt)
            parsed = self._parse_json_response(raw_response)
        except (ValueError, TypeError, KeyError) as exc:
            raise MemoryConsolidationError(
                message=f"Conversation extraction LLM call failed: {exc}",
                strategy="conversation_extraction",
                cause=exc,
            ) from exc

        raw_entities: list[dict[str, Any]] = parsed.get("entities", [])
        raw_relations: list[dict[str, Any]] = parsed.get("relations", [])

        # Normalise entity dicts
        entities: list[dict[str, Any]] = []
        for raw_ent in raw_entities:
            entities.append(
                {
                    "name": str(raw_ent.get("name", "")),
                    "type": str(raw_ent.get("type", "entity")),
                    "attributes": raw_ent.get("attributes", {}),
                }
            )

        # Normalise relation dicts
        relations: list[dict[str, Any]] = []
        for raw_rel in raw_relations:
            relations.append(
                {
                    "subject": str(raw_rel.get("subject", "")),
                    "predicate": str(raw_rel.get("predicate", "")),
                    "object": str(raw_rel.get("object", "")),
                }
            )

        return entities, relations

    # ------------------------------------------------------------------
    # Regex-based fallback extraction
    # ------------------------------------------------------------------

    async def _extract_with_regex(
        self,
        user_message: str,
        assistant_message: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Fallback extraction using regex proper-noun detection.

        Args:
            user_message: User message text.
            assistant_message: Assistant response text.

        Returns:
            Tuple of (entities list, empty relations list).
        """
        combined_text = f"{user_message} {assistant_message}"
        matches = _PROPER_NOUN_PATTERN.findall(combined_text)

        # Deduplicate while preserving order
        seen: set[str] = set()
        entities: list[dict[str, Any]] = []
        for match in matches:
            normalised = match.strip()
            if normalised and normalised not in seen:
                seen.add(normalised)
                entities.append(
                    {
                        "name": normalised,
                        "type": "entity",
                        "attributes": {"extraction_method": "regex"},
                    }
                )

        return entities, []

    # ------------------------------------------------------------------
    # Contradiction detection fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_contradictions_simple(
        new_facts: list[str],
        existing_facts: list[str],
    ) -> list[Contradiction]:
        """
        Simple heuristic contradiction detection without LLM.

        Compares new and existing facts by checking whether they share a
        subject prefix but differ in their predicate/object portion.

        Args:
            new_facts: Newly extracted facts.
            existing_facts: Previously stored facts.

        Returns:
            List of detected contradictions.
        """
        contradictions: list[Contradiction] = []
        for new_fact in new_facts:
            new_lower = new_fact.lower().strip()
            for existing_fact in existing_facts:
                existing_lower = existing_fact.lower().strip()
                # Simple overlap heuristic: same first 3 words but different overall
                new_words = new_lower.split()
                existing_words = existing_lower.split()
                if (
                    len(new_words) >= 3
                    and len(existing_words) >= 3
                    and new_words[:3] == existing_words[:3]
                    and new_lower != existing_lower
                ):
                    contradictions.append(
                        Contradiction(
                            existing_fact=existing_fact,
                            new_fact=new_fact,
                            conflict_type="attribute_change",
                            resolution="flag_for_review",
                        )
                    )
        return contradictions

    # ------------------------------------------------------------------
    # Coreference resolution fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_coreferences_simple(
        entities: list[dict[str, Any]],
        existing_entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Simple name-matching coreference resolution without LLM.

        Merges entities that share the same normalised name, combining
        attributes with newer values taking precedence.

        Args:
            entities: Newly extracted entities.
            existing_entities: Previously known entities.

        Returns:
            Resolved entity list.
        """
        existing_by_name: dict[str, dict[str, Any]] = {
            ent.get("name", "").lower(): ent for ent in existing_entities
        }

        resolved: list[dict[str, Any]] = []
        for entity in entities:
            key = entity.get("name", "").lower()
            if key in existing_by_name:
                existing = existing_by_name[key]
                merged_attrs = {
                    **existing.get("attributes", {}),
                    **entity.get("attributes", {}),
                }
                resolved.append(
                    {
                        "name": existing.get("name", entity.get("name", "")),
                        "type": existing.get("type", entity.get("type", "entity")),
                        "attributes": merged_attrs,
                    }
                )
            else:
                resolved.append(entity)

        return resolved

    # ------------------------------------------------------------------
    # Memory entry construction
    # ------------------------------------------------------------------

    def _build_memory_entries(
        self,
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        security_context: SecurityContext,
    ) -> list[MemoryEntry]:
        """
        Build MemoryEntry objects from extracted entities and relations.

        Creates one episodic entry for the conversation turn and one
        semantic entry per extracted entity.

        Args:
            entities: Extracted entities.
            relations: Extracted relations.
            conversation_id: Conversation identifier.
            user_message: Original user message.
            assistant_message: Original assistant response.
            security_context: Security context.

        Returns:
            List of MemoryEntry objects.
        """
        entries: list[MemoryEntry] = []
        now = datetime.now(UTC)

        # Episodic entry for the full conversation turn
        turn_content = f"User: {user_message}\nAssistant: {assistant_message}"
        entries.append(
            MemoryEntry(
                id=f"mem_{uuid.uuid4().hex[:12]}",
                tier=MemoryTier.EPISODIC,
                scope=MemoryScope.USER,
                content=MemoryContent(
                    content=turn_content,
                    content_type="conversation",
                    metadata={
                        "conversation_id": conversation_id,
                        "user_id": security_context.user_id,
                        "entity_count": len(entities),
                        "relation_count": len(relations),
                    },
                    token_count=len(turn_content.split()),
                ),
                importance=0.5,
                access_count=0,
                created_at=now,
                tags=["conversation", conversation_id],
                metadata={
                    "source": "conversation_extractor",
                    "conversation_id": conversation_id,
                },
            )
        )

        # Semantic entries for each extracted entity
        for entity in entities:
            entity_name = entity.get("name", "unknown")
            entity_type = entity.get("type", "entity")
            entity_attrs = entity.get("attributes", {})

            content_parts = [f"{entity_name} ({entity_type})"]
            for attr_key, attr_val in entity_attrs.items():
                content_parts.append(f"  {attr_key}: {attr_val}")

            entity_content = "\n".join(content_parts)
            importance = 0.6 if entity_type in ("person", "organization") else 0.4

            entries.append(
                MemoryEntry(
                    id=f"mem_{uuid.uuid4().hex[:12]}",
                    tier=MemoryTier.SEMANTIC,
                    scope=MemoryScope.USER,
                    content=MemoryContent(
                        content=entity_content,
                        content_type="entity",
                        metadata={
                            "entity_name": entity_name,
                            "entity_type": entity_type,
                            "conversation_id": conversation_id,
                        },
                        token_count=len(entity_content.split()),
                    ),
                    importance=importance,
                    access_count=0,
                    created_at=now,
                    tags=["entity", entity_type, conversation_id],
                    metadata={
                        "source": "conversation_extractor",
                        "entity_name": entity_name,
                        "entity_type": entity_type,
                    },
                )
            )

        return entries

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_response(raw_response: str) -> dict[str, Any]:
        """
        Parse a JSON response from the LLM, tolerating markdown fences.

        Args:
            raw_response: Raw LLM output string.

        Returns:
            Parsed dictionary.

        Raises:
            ValueError: If no valid JSON can be extracted.
        """
        text = raw_response.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Try direct parse first
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
            raise ValueError(f"Expected JSON object, got {type(result).__name__}")
        except json.JSONDecodeError:
            pass

        # Fallback: find first JSON object in text
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            try:
                result = json.loads(brace_match.group(0))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")
