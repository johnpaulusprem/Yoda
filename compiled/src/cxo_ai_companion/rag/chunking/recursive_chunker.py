"""Recursive character-based text chunker with overlap support."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from cxo_ai_companion.rag.chunking.base_chunker import (
    BaseChunker,
    Chunk,
    ChunkerConfig,
    ChunkMetadata,
)

logger = logging.getLogger(__name__)


@dataclass
class RecursiveChunkerConfig(ChunkerConfig):
    """Configuration for the recursive character-based chunker.

    Attributes:
        separators: Ordered tuple of separator strings tried from highest
            to lowest priority (paragraph, line, sentence, word).
        keep_separator: Whether to retain the separator at the start of
            each resulting piece.
    """

    separators: tuple[str, ...] = ("\n\n", "\n", ". ", " ")
    keep_separator: bool = True


class RecursiveChunker(BaseChunker):
    """Splits text into overlapping chunks using a separator hierarchy.

    Recursively tries separators in priority order (paragraph, line,
    sentence, word). Produces chunks of approximately ``chunk_size``
    characters with ``chunk_overlap`` characters of context carried
    between consecutive chunks.

    Args:
        config: Recursive chunker configuration. Defaults to
            ``RecursiveChunkerConfig()``.
    """

    def __init__(self, config: RecursiveChunkerConfig | None = None) -> None:
        resolved = config or RecursiveChunkerConfig()
        super().__init__(resolved)
        self.config: RecursiveChunkerConfig = resolved

    def chunk(self, text: str) -> list[Chunk]:
        """Split text into chunks without document context.

        Uses ``"unknown"`` as the document ID.

        Args:
            text: Raw document text.

        Returns:
            A list of :class:`Chunk` objects.
        """
        return self.chunk_document("unknown", text)

    def chunk_document(self, document_id: str, text: str) -> list[Chunk]:
        """Split text into chunks associated with a specific document.

        1. Recursively split using the configured separator hierarchy.
        2. Merge small pieces and apply overlap.
        3. Build :class:`Chunk` objects with positional metadata.
        4. Filter out chunks below ``min_chunk_size``.

        Args:
            document_id: Unique identifier for the source document.
            text: Raw document text.

        Returns:
            A list of :class:`Chunk` objects ordered by position.
        """
        if not text or not text.strip():
            return []

        # Step 1 -- recursive split
        raw_splits = self._recursive_split(text, self.config.separators)

        # Step 2 -- merge with overlap
        merged = self._merge_with_overlap(raw_splits)

        # Step 3 -- build Chunk objects, tracking character offsets
        chunks: list[Chunk] = []
        search_start = 0

        for idx, piece in enumerate(merged):
            # Find the position of this piece in the original text.
            # Because overlap can duplicate content, we search forward.
            start_char = text.find(piece[:50], search_start) if len(piece) >= 50 else text.find(piece, search_start)
            if start_char == -1:
                # Fallback: search from the beginning (overlap may have
                # caused us to skip ahead too far).
                start_char = text.find(piece[:50]) if len(piece) >= 50 else text.find(piece)
            if start_char == -1:
                start_char = search_start

            end_char = start_char + len(piece)
            search_start = start_char + 1

            token_count = self._estimate_tokens(piece)

            meta = ChunkMetadata(
                chunk_id=uuid.uuid4().hex,
                document_id=document_id,
                chunk_index=idx,
                start_char=start_char,
                end_char=end_char,
                token_count=token_count,
            )
            chunks.append(Chunk(content=piece, metadata=meta))

        # Step 4 -- filter out chunks that are too small
        chunks = [c for c in chunks if len(c.content) >= self.config.min_chunk_size]

        # Re-index after filtering
        for idx, chunk in enumerate(chunks):
            chunk.metadata.chunk_index = idx

        logger.debug(
            "Chunked document %s into %d chunks (from %d chars)",
            document_id,
            len(chunks),
            len(text),
        )
        return chunks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _recursive_split(
        self, text: str, separators: tuple[str, ...]
    ) -> list[str]:
        """Recursively split *text* using *separators* in priority order.

        If the text fits within ``chunk_size`` or no separators remain,
        it is returned as-is.  Otherwise the first separator is used
        and any oversized pieces are split again with the remaining
        separators.

        Args:
            text: Text to split.
            separators: Ordered tuple of separator strings.

        Returns:
            A list of text pieces, each ideally within ``chunk_size``.
        """
        if len(text) <= self.config.chunk_size:
            return [text]

        if not separators:
            # No separators left -- hard-split at chunk_size boundaries
            pieces: list[str] = []
            for i in range(0, len(text), self.config.chunk_size):
                pieces.append(text[i : i + self.config.chunk_size])
            return pieces

        sep = separators[0]
        remaining_seps = separators[1:]

        raw_parts = text.split(sep)
        result: list[str] = []

        for i, part in enumerate(raw_parts):
            if not part and not self.config.keep_separator:
                continue

            # Re-attach the separator to the beginning of the piece
            # (except the very first one) when keep_separator is True.
            if self.config.keep_separator and i > 0:
                piece = sep + part
            else:
                piece = part

            if not piece:
                continue

            if len(piece) <= self.config.chunk_size:
                result.append(piece)
            else:
                # Piece is still too large -- recurse with next separator
                result.extend(self._recursive_split(piece, remaining_seps))

        return result

    def _merge_with_overlap(self, splits: list[str]) -> list[str]:
        """Merge consecutive small splits and apply overlap.

        Pieces are accumulated until adding the next one would exceed
        ``chunk_size``.  When a merged chunk is finalised, the last
        ``chunk_overlap`` characters become the prefix of the next chunk.

        Args:
            splits: Small text pieces produced by :meth:`_recursive_split`.

        Returns:
            A list of merged text pieces with overlap applied.
        """
        if not splits:
            return []

        merged: list[str] = []
        current_parts: list[str] = []
        current_length = 0

        for piece in splits:
            piece_len = len(piece)

            if current_length + piece_len > self.config.chunk_size and current_parts:
                # Flush current buffer
                merged_text = "".join(current_parts)
                merged.append(merged_text)

                # Calculate overlap: take the tail of the merged text
                overlap_text = merged_text[-self.config.chunk_overlap :] if self.config.chunk_overlap > 0 else ""

                current_parts = []
                current_length = 0

                if overlap_text:
                    current_parts.append(overlap_text)
                    current_length = len(overlap_text)

            current_parts.append(piece)
            current_length += piece_len

        # Flush remaining buffer
        if current_parts:
            merged.append("".join(current_parts))

        return merged
