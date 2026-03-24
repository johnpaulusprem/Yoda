"""Azure OpenAI embedding provider using the AsyncAzureOpenAI client."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from openai import AsyncAzureOpenAI

from yoda_foundation.rag.embeddings.base_embedder import (
    BaseEmbedder,
    EmbedderConfig,
    EmbeddingResult,
)

logger = logging.getLogger(__name__)


@dataclass
class AzureEmbedderConfig(EmbedderConfig):
    """Configuration specific to the Azure OpenAI embedding service.

    Attributes:
        azure_endpoint: Azure OpenAI resource endpoint URL.
        api_key: API key for the Azure OpenAI resource.
        deployment_name: Name of the deployed embedding model.
        api_version: Azure OpenAI API version string.
    """

    azure_endpoint: str = ""
    api_key: str = ""
    deployment_name: str = "text-embedding-3-small"
    api_version: str = "2024-02-01"


class AzureEmbedder(BaseEmbedder):
    """Embedding provider backed by Azure OpenAI Embeddings API.

    Supports single-text and batched embedding with automatic
    chunking of large batches according to ``config.batch_size``.

    Args:
        config: Azure-specific embedder configuration including endpoint
            and credentials.
    """

    def __init__(self, config: AzureEmbedderConfig) -> None:
        super().__init__(config)
        self.config: AzureEmbedderConfig = config
        self._client = AsyncAzureOpenAI(
            azure_endpoint=config.azure_endpoint,
            api_key=config.api_key,
            api_version=config.api_version,
        )

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text.

        Args:
            text: The input text to embed.

        Returns:
            A list of floats representing the embedding vector.
        """
        validated = self.validate_text(text)
        logger.debug("Embedding single text (%d chars)", len(validated))
        response = await self._client.embeddings.create(
            input=[validated],
            model=self.config.deployment_name,
            dimensions=self.config.dimensions,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> EmbeddingResult:
        """Generate embedding vectors for a batch of texts.

        Texts are validated, then processed in sub-batches of
        ``config.batch_size``.  Timing is tracked for observability.

        Args:
            texts: A list of input texts to embed.

        Returns:
            An :class:`EmbeddingResult` containing all vectors and metadata.
        """
        validated_texts = [self.validate_text(t) for t in texts]
        total_tokens = 0
        all_vectors: list[list[float]] = []

        start = time.perf_counter()

        for batch_start in range(0, len(validated_texts), self.config.batch_size):
            batch = validated_texts[batch_start : batch_start + self.config.batch_size]
            logger.debug(
                "Embedding batch %d-%d of %d texts",
                batch_start,
                batch_start + len(batch),
                len(validated_texts),
            )

            response = await self._client.embeddings.create(
                input=batch,
                model=self.config.deployment_name,
                dimensions=self.config.dimensions,
            )

            for item in response.data:
                all_vectors.append(item.embedding)

            if response.usage is not None:
                total_tokens += response.usage.total_tokens

        elapsed_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "Embedded %d texts in %.1f ms (%d tokens)",
            len(validated_texts),
            elapsed_ms,
            total_tokens,
        )

        return EmbeddingResult(
            vectors=all_vectors,
            dimensions=self.config.dimensions,
            token_count=total_tokens,
            execution_time_ms=elapsed_ms,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client and release resources."""
        await self._client.close()
        logger.debug("AzureEmbedder client closed")
