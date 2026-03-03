"""Base document loader infrastructure for the RAG ingestion pipeline.

Defines the abstract base class and shared data structures that all
format-specific document loaders implement.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class LoadMode(Enum):
    """Strategy for splitting a document during loading.

    Controls whether the loader returns the entire document as a single unit,
    splits by pages/slides, or splits by sections/headings.
    """

    SINGLE = "single"    # Entire document as one LoadedDocument
    PAGE = "page"        # Split by pages (PDF pages, PPTX slides, etc.)
    SECTION = "section"  # Split by sections / headings


@dataclass
class DocumentMetadata:
    """Metadata extracted from a loaded document.

    Captures authorship, size, and arbitrary extra properties discovered
    during the loading process.
    """

    title: str = ""
    author: str = ""
    page_count: int = 0
    word_count: int = 0
    created_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoadedDocument:
    """A loaded document (or page/section of a document).

    Named ``LoadedDocument`` rather than ``Document`` to avoid collision
    with the SQLAlchemy ``Document`` model used elsewhere in the codebase.
    """

    content: str
    source: str
    document_id: str = ""
    mime_type: str = ""
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    page_number: int | None = None


@dataclass
class LoaderConfig:
    """Shared configuration accepted by every loader.

    Attributes:
        mode: How to split the document (single, page, or section).
        encoding: Text encoding for file reads (default ``utf-8``).
        max_size_mb: Maximum allowed file size in megabytes.
        extract_metadata: Whether to extract document metadata during loading.
    """

    mode: LoadMode = LoadMode.SINGLE
    encoding: str = "utf-8"
    max_size_mb: float = 50.0
    extract_metadata: bool = True


class DocumentLoader(ABC):
    """Abstract base class for document format loaders.

    Subclasses implement ``load`` for a specific file format (PDF, DOCX, etc.)
    and ``supports_source`` to declare which file extensions they handle.

    Args:
        config: Shared loader configuration. Defaults to ``LoaderConfig()``.
    """

    def __init__(self, config: LoaderConfig | None = None) -> None:
        self.config = config or LoaderConfig()

    @abstractmethod
    async def load(self, source: str | bytes) -> list[LoadedDocument]:
        """Load document from a file path or raw bytes.

        Args:
            source: Either a filesystem path (``str``) or the raw file
                content (``bytes``).

        Returns:
            One or more loaded documents depending on the configured
            :pyattr:`LoadMode`.
        """
        ...

    async def load_batch(self, sources: list[str | bytes]) -> list[LoadedDocument]:
        """Load multiple documents sequentially.

        Args:
            sources: A list of file paths or byte payloads to load.

        Returns:
            A flat list of all loaded documents across all sources.
        """
        results: list[LoadedDocument] = []
        for source in sources:
            try:
                docs = await self.load(source)
                results.extend(docs)
            except Exception:
                logger.exception("Failed to load source %s", source if isinstance(source, str) else "<bytes>")
        return results

    @abstractmethod
    def supports_source(self, source: str) -> bool:
        """Return ``True`` if this loader can handle *source* (by extension)."""
        ...

    def _validate_size(self, data: bytes) -> None:
        """Raise ``ValueError`` if *data* exceeds the configured size limit."""
        size_mb = len(data) / (1024 * 1024)
        if size_mb > self.config.max_size_mb:
            raise ValueError(
                f"File size {size_mb:.1f}MB exceeds limit of {self.config.max_size_mb}MB"
            )

    def _count_words(self, text: str) -> int:
        """Return a rough word count for *text*."""
        return len(text.split())


__all__ = [
    "DocumentLoader",
    "DocumentMetadata",
    "LoadedDocument",
    "LoaderConfig",
    "LoadMode",
]
