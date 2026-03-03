"""Abstract base embedder and shared data structures for embedding providers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EmbedderConfig:
    """Configuration for an embedding provider.

    Attributes:
        model_name: Name or deployment of the embedding model.
        dimensions: Dimensionality of the output embedding vectors.
        batch_size: Maximum number of texts per embedding API call.
        max_tokens: Maximum estimated tokens allowed per input text.
        timeout: HTTP request timeout in seconds.
    """

    model_name: str = "text-embedding-3-small"
    dimensions: int = 1536
    batch_size: int = 100
    max_tokens: int = 8191
    timeout: float = 30.0


@dataclass
class EmbeddingResult:
    """Result of a batch embedding operation.

    Attributes:
        vectors: List of embedding vectors, one per input text.
        dimensions: Dimensionality of each vector.
        token_count: Total tokens consumed across all texts.
        execution_time_ms: Wall-clock time for the batch in milliseconds.
    """

    vectors: list[list[float]]
    dimensions: int
    token_count: int
    execution_time_ms: float


class BaseEmbedder(ABC):
    """Abstract base class for all embedding providers.

    Subclasses must implement :meth:`embed` (single text) and
    :meth:`embed_batch` (multiple texts). The :meth:`validate_text`
    helper is provided for common pre-processing.

    Args:
        config: Embedder configuration controlling model, dimensions, and limits.
    """

    def __init__(self, config: EmbedderConfig) -> None:
        self.config = config

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text.

        Args:
            text: The input text to embed.

        Returns:
            A list of floats representing the embedding vector.
        """

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> EmbeddingResult:
        """Generate embedding vectors for a batch of texts.

        Args:
            texts: A list of input texts to embed.

        Returns:
            An :class:`EmbeddingResult` containing all vectors and metadata.
        """

    def validate_text(self, text: str) -> str:
        """Strip whitespace, verify non-empty, and check rough token limit.

        Args:
            text: Raw input text.

        Returns:
            The cleaned text ready for embedding.

        Raises:
            ValueError: If the text is empty or exceeds the token limit.
        """
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Text must not be empty after stripping whitespace")

        estimated_tokens = len(cleaned) // 4
        if estimated_tokens > self.config.max_tokens:
            raise ValueError(
                f"Text exceeds estimated token limit: ~{estimated_tokens} tokens "
                f"(max {self.config.max_tokens})"
            )

        return cleaned


__all__ = [
    "EmbedderConfig",
    "EmbeddingResult",
    "BaseEmbedder",
]
