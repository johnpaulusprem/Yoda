"""Abstract base chunker and shared data structures for document chunking."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ChunkerConfig:
    """Configuration for a document chunker.

    Attributes:
        chunk_size: Target chunk size in characters.
        chunk_overlap: Number of overlapping characters between consecutive chunks.
        min_chunk_size: Minimum chunk size; smaller chunks are discarded.
    """

    chunk_size: int = 1000
    chunk_overlap: int = 200
    min_chunk_size: int = 100


@dataclass
class ChunkMetadata:
    """Positional and identification metadata for a single chunk.

    Attributes:
        chunk_id: Unique identifier for this chunk.
        document_id: Identifier of the source document.
        chunk_index: Zero-based position of this chunk within the document.
        start_char: Start character offset in the original text.
        end_char: End character offset in the original text.
        token_count: Estimated token count for this chunk.
    """

    chunk_id: str
    document_id: str
    chunk_index: int
    start_char: int
    end_char: int
    token_count: int


@dataclass
class Chunk:
    """A chunk of document text with its metadata and optional embedding."""

    content: str
    metadata: ChunkMetadata
    embedding: list[float] | None = None


class BaseChunker(ABC):
    """Abstract base class for document chunking strategies.

    Subclasses must implement :meth:`chunk` (context-free splitting) and
    :meth:`chunk_document` (splitting with a known document ID).

    Args:
        config: Chunker configuration controlling size, overlap, and minimum.
    """

    def __init__(self, config: ChunkerConfig) -> None:
        self.config = config

    @abstractmethod
    def chunk(self, text: str) -> list[Chunk]:
        """Split text into chunks without document context.

        Args:
            text: Raw document text.

        Returns:
            A list of :class:`Chunk` objects.
        """

    @abstractmethod
    def chunk_document(self, document_id: str, text: str) -> list[Chunk]:
        """Split text into chunks associated with a specific document.

        Args:
            document_id: Unique identifier for the source document.
            text: Raw document text.

        Returns:
            A list of :class:`Chunk` objects with proper metadata.
        """

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate (1 token ~= 4 characters).

        Args:
            text: Input text.

        Returns:
            Estimated token count.
        """
        return len(text) // 4
