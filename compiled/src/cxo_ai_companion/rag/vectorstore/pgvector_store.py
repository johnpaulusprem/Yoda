"""PostgreSQL + pgvector backed vector store implementation."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cxo_ai_companion.rag.vectorstore.base_vectorstore import (
    BaseVectorStore,
    DistanceMetric,
    VectorDocument,
    VectorSearchResult,
)

logger = logging.getLogger(__name__)


@dataclass
class PGVectorConfig:
    """Configuration for the pgvector-backed vector store.

    Attributes:
        table_name: PostgreSQL table storing document chunks and embeddings.
        index_type: Index algorithm (``hnsw`` or ``ivfflat``).
        dimensions: Dimensionality of embedding vectors.
        distance_metric: Distance function used for similarity search.
        ef_construction: HNSW index build-time accuracy parameter.
        m: HNSW maximum number of connections per node.
    """

    table_name: str = "document_chunks"
    index_type: str = "hnsw"
    dimensions: int = 1536
    distance_metric: DistanceMetric = DistanceMetric.COSINE
    ef_construction: int = 64
    m: int = 16

    def __post_init__(self) -> None:
        import re
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", self.table_name):
            raise ValueError(
                f"Invalid table_name '{self.table_name}': must match ^[a-zA-Z_][a-zA-Z0-9_]*$"
            )


class PGVectorStore(BaseVectorStore):
    """Vector store backed by PostgreSQL with the pgvector extension.

    Uses raw SQL via :func:`sqlalchemy.text` to leverage pgvector
    distance operators directly against the ``document_chunks`` table.

    Args:
        session_factory: SQLAlchemy async session factory for database access.
        config: pgvector-specific configuration. Defaults to ``PGVectorConfig()``.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        config: PGVectorConfig | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config = config or PGVectorConfig()

    @property
    def config(self) -> PGVectorConfig:
        """Return the pgvector configuration."""
        return self._config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upsert(self, documents: list[VectorDocument]) -> int:
        """Insert or update document chunks.

        Maps :class:`VectorDocument` fields onto the ``document_chunks``
        table columns.  Uses PostgreSQL ``ON CONFLICT`` for upsert semantics.

        Args:
            documents: Documents to upsert.

        Returns:
            The number of rows affected.
        """
        if not documents:
            return 0

        upserted = 0
        async with self._session_factory() as session:
            for doc in documents:
                doc_uuid = uuid.UUID(doc.id) if isinstance(doc.id, str) else doc.id
                vector_str = "[" + ",".join(str(v) for v in doc.vector) + "]"
                metadata_json = json.dumps(doc.metadata) if doc.metadata else None

                # Extract document_id and chunk_index from metadata when available
                document_id = doc.metadata.get("document_id") if doc.metadata else None
                chunk_index = doc.metadata.get("chunk_index", 0) if doc.metadata else 0
                token_count = doc.metadata.get("token_count", 0) if doc.metadata else 0

                stmt = text(
                    f"""
                    INSERT INTO {self._config.table_name}
                        (id, document_id, chunk_index, content, embedding, token_count, metadata, created_at, updated_at)
                    VALUES
                        (:id, :document_id, :chunk_index, :content, :embedding::vector, :token_count, :metadata::jsonb, now(), now())
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        token_count = EXCLUDED.token_count,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    """
                )

                await session.execute(
                    stmt,
                    {
                        "id": doc_uuid,
                        "document_id": uuid.UUID(document_id) if document_id else None,
                        "chunk_index": chunk_index,
                        "content": doc.content,
                        "embedding": vector_str,
                        "token_count": token_count,
                        "metadata": metadata_json,
                    },
                )
                upserted += 1

            await session.commit()

        logger.info("Upserted %d document chunks", upserted)
        return upserted

    async def search(
        self,
        query_vector: list[float],
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Perform cosine similarity search using pgvector.

        Uses the ``<=>`` cosine distance operator.  Optional metadata
        filters are applied as JSONB containment checks.

        Args:
            query_vector: The query embedding vector.
            k: Number of results to return.
            filters: Optional metadata key/value pairs used as JSONB filters.

        Returns:
            A list of :class:`VectorSearchResult` ordered by descending
            similarity score (higher is better).
        """
        vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

        where_clauses: list[str] = []
        params: dict[str, Any] = {
            "query_vector": vector_str,
            "k": k,
        }

        if filters:
            for idx, (key, value) in enumerate(filters.items()):
                param_name = f"filter_{idx}"
                where_clauses.append(
                    f"metadata @> :{param_name}::jsonb"
                )
                params[param_name] = json.dumps({key: value})

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        query = text(
            f"""
            SELECT
                id,
                content,
                metadata,
                embedding::text,
                (embedding <=> :query_vector::vector) AS distance
            FROM {self._config.table_name}
            {where_sql}
            ORDER BY distance ASC
            LIMIT :k
            """
        )

        results: list[VectorSearchResult] = []
        async with self._session_factory() as session:
            rows = await session.execute(query, params)

            for rank, row in enumerate(rows, start=1):
                row_id, content, metadata, embedding_text, distance = row
                # Parse the vector text back into a list of floats
                vector = self._parse_vector_text(embedding_text)
                meta = metadata if isinstance(metadata, dict) else {}

                doc = VectorDocument(
                    id=str(row_id),
                    vector=vector,
                    content=content,
                    metadata=meta,
                )
                # Score = 1 - cosine_distance so higher is more similar
                score = 1.0 - float(distance)
                results.append(
                    VectorSearchResult(document=doc, score=score, rank=rank)
                )

        logger.debug("Vector search returned %d results", len(results))
        return results

    async def delete(self, ids: list[str]) -> int:
        """Delete document chunks by ID.

        Args:
            ids: Chunk IDs to delete.

        Returns:
            The number of rows actually deleted.
        """
        if not ids:
            return 0

        id_uuids = [uuid.UUID(i) if isinstance(i, str) else i for i in ids]
        placeholders = ", ".join(f":id_{idx}" for idx in range(len(id_uuids)))
        params = {f"id_{idx}": uid for idx, uid in enumerate(id_uuids)}

        stmt = text(
            f"DELETE FROM {self._config.table_name} WHERE id IN ({placeholders})"
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt, params)
            await session.commit()
            deleted = result.rowcount  # type: ignore[union-attr]

        logger.info("Deleted %d document chunks", deleted)
        return deleted

    async def get(self, id: str) -> VectorDocument | None:
        """Retrieve a single document chunk by its ID.

        Args:
            id: The chunk UUID as a string.

        Returns:
            The :class:`VectorDocument`, or ``None`` if not found.
        """
        doc_uuid = uuid.UUID(id) if isinstance(id, str) else id
        stmt = text(
            f"""
            SELECT id, content, metadata, embedding::text
            FROM {self._config.table_name}
            WHERE id = :id
            """
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt, {"id": doc_uuid})
            row = result.one_or_none()

        if row is None:
            return None

        row_id, content, metadata, embedding_text = row
        vector = self._parse_vector_text(embedding_text)
        meta = metadata if isinstance(metadata, dict) else {}

        return VectorDocument(
            id=str(row_id),
            vector=vector,
            content=content,
            metadata=meta,
        )

    async def count(self) -> int:
        """Return the total number of chunks in the store."""
        stmt = text(f"SELECT count(*) FROM {self._config.table_name}")

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            row = result.scalar_one()

        return int(row)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_vector_text(vector_text: str | None) -> list[float]:
        """Parse a pgvector text representation back to a list of floats.

        pgvector returns vectors as strings like ``[0.1,0.2,0.3]``.
        """
        if not vector_text:
            return []
        cleaned = vector_text.strip().strip("[]")
        if not cleaned:
            return []
        return [float(v) for v in cleaned.split(",")]
