"""Citation tracking and bibliography formatting for RAG responses."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_CITATION_PATTERN = re.compile(r"\[(\d+)\]")


@dataclass
class SourceReference:
    """A reference to a source document.

    Attributes:
        source_id: Unique identifier for the source.
        title: Human-readable title of the source.
        url: Optional URL where the source can be accessed.
        document_id: Optional identifier of the parent document.
        chunk_index: Optional index of the chunk within the parent document.
        metadata: Additional metadata associated with the source.
    """

    source_id: str
    title: str
    url: str | None = None
    document_id: str | None = None
    chunk_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Citation:
    """A citation linking a numbered marker to its source.

    Attributes:
        index: The 1-based citation number (e.g. ``1`` for ``[1]``).
        source: The source reference this citation points to.
        text_snippet: A short excerpt from the cited content.
        relevance_score: The relevance score associated with this citation.
    """

    index: int
    source: SourceReference
    text_snippet: str = ""
    relevance_score: float = 0.0


class CitationTracker:
    """Tracks citations and sources used in a RAG-generated response.

    Provides methods to register sources, look up citations, produce
    a formatted bibliography, and resolve ``[N]`` markers found in text.
    """

    def __init__(self) -> None:
        self._citations: list[Citation] = []
        self._source_map: dict[str, SourceReference] = {}

    def add_source(self, source: SourceReference) -> int:
        """Register a source and return its citation index.

        If the source has already been registered (matched by
        :pyattr:`SourceReference.source_id`), the existing citation
        index is returned without creating a duplicate.

        Args:
            source: The source reference to register.

        Returns:
            The 1-based citation index assigned to this source.
        """
        if source.source_id in self._source_map:
            for citation in self._citations:
                if citation.source.source_id == source.source_id:
                    logger.debug(
                        "Source %r already registered as citation [%d]",
                        source.source_id,
                        citation.index,
                    )
                    return citation.index
            # Defensive: source_map had the key but no matching citation.
            # Fall through to create a new citation.

        index = len(self._citations) + 1
        self._source_map[source.source_id] = source

        citation = Citation(index=index, source=source)
        self._citations.append(citation)

        logger.debug(
            "Registered source %r as citation [%d]",
            source.source_id,
            index,
        )

        return index

    def get_citation(self, index: int) -> Citation | None:
        """Look up a citation by its 1-based index.

        Args:
            index: The citation number to look up.

        Returns:
            The :class:`Citation` if found, otherwise ``None``.
        """
        if 1 <= index <= len(self._citations):
            return self._citations[index - 1]
        return None

    def get_all_citations(self) -> list[Citation]:
        """Return all registered citations.

        Returns:
            A list of all :class:`Citation` objects in index order.
        """
        return list(self._citations)

    def format_bibliography(self) -> str:
        """Format all citations as a numbered bibliography.

        Returns:
            A newline-separated string with entries like
            ``[1] Title (URL)`` or ``[1] Title`` when no URL is set.
        """
        lines: list[str] = []
        for citation in self._citations:
            source = citation.source
            if source.url:
                lines.append(f"[{citation.index}] {source.title} ({source.url})")
            else:
                lines.append(f"[{citation.index}] {source.title}")

        return "\n".join(lines)

    def resolve_citations(self, text: str) -> list[Citation]:
        """Scan text for ``[N]`` citation markers and return matching citations.

        Only markers whose index corresponds to a registered citation are
        included.  Duplicate indices in the text produce only a single
        entry in the returned list.

        Args:
            text: The text to scan for citation markers.

        Returns:
            A list of :class:`Citation` objects for every resolved marker,
            in the order they first appear in the text.
        """
        seen: set[int] = set()
        resolved: list[Citation] = []

        for match in _CITATION_PATTERN.finditer(text):
            index = int(match.group(1))
            if index in seen:
                continue
            seen.add(index)

            citation = self.get_citation(index)
            if citation is not None:
                resolved.append(citation)
            else:
                logger.warning(
                    "Citation marker [%d] found in text but no matching source",
                    index,
                )

        return resolved


__all__ = [
    "CitationTracker",
    "SourceReference",
    "Citation",
]
