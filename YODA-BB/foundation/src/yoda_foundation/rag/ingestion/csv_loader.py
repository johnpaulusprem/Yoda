"""CSV / tabular document loader using the stdlib csv module."""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from enum import Enum

from yoda_foundation.rag.ingestion.base_loader import (
    DocumentLoader,
    DocumentMetadata,
    LoadedDocument,
    LoaderConfig,
)

logger = logging.getLogger(__name__)


class CSVLoadMode(Enum):
    """Strategy for converting CSV rows into plain-text representation.

    ``ROW_BASED`` produces ``"header: value; header: value"`` per row.
    ``CELL_BASED`` produces ``"cell | cell | cell"`` per row.
    """

    ROW_BASED = "row_based"    # Each row = "header: value; header: value"
    CELL_BASED = "cell_based"  # Each row = "cell | cell | cell"


@dataclass
class TabularConfig(LoaderConfig):
    """CSV-specific loader configuration.

    Attributes:
        csv_mode: Text representation strategy for CSV rows.
        delimiter: Column delimiter character.
        has_header: Whether the first row is a header row.
        max_rows: Maximum number of data rows to process.
    """

    csv_mode: CSVLoadMode = CSVLoadMode.ROW_BASED
    delimiter: str = ","
    has_header: bool = True
    max_rows: int = 10000


class CSVLoader(DocumentLoader):
    """Load text content from CSV files.

    Parses the CSV, applies header detection and row limits, and converts
    rows into a plain-text representation controlled by :class:`CSVLoadMode`.

    Args:
        config: Tabular-specific configuration. Defaults to ``TabularConfig()``.
    """

    def __init__(self, config: TabularConfig | None = None) -> None:
        super().__init__(config or TabularConfig())

    @property
    def tabular_config(self) -> TabularConfig:
        """Return the config cast to ``TabularConfig``."""
        return self.config  # type: ignore[return-value]

    async def load(self, source: str | bytes) -> list[LoadedDocument]:
        """Load a CSV from a file path or raw bytes.

        The CSV is parsed and converted into a text representation
        controlled by :class:`CSVLoadMode`.
        """
        if isinstance(source, str):
            try:
                with open(source, "r", encoding=self.config.encoding) as f:
                    content = f.read()
            except Exception as exc:
                logger.error("Failed to read CSV file %s: %s", source, exc)
                raise
            source_name = source
        else:
            self._validate_size(source)
            content = source.decode(self.config.encoding)
            source_name = "bytes_input"

        reader = csv.reader(
            io.StringIO(content),
            delimiter=self.tabular_config.delimiter,
        )
        rows = list(reader)

        if not rows:
            logger.warning("CSV %s is empty", source_name)
            return []

        # ---- Headers ---------------------------------------------------
        if self.tabular_config.has_header:
            headers = rows[0]
            data_rows = rows[1:]
        else:
            headers = [f"col_{i}" for i in range(len(rows[0]))]
            data_rows = rows

        # ---- Limit rows -----------------------------------------------
        data_rows = data_rows[: self.tabular_config.max_rows]

        # ---- Build text representation --------------------------------
        if self.tabular_config.csv_mode == CSVLoadMode.ROW_BASED:
            text_parts: list[str] = []
            for row in data_rows:
                row_text = "; ".join(
                    f"{h}: {v}" for h, v in zip(headers, row) if v.strip()
                )
                if row_text:
                    text_parts.append(row_text)
            full_text = "\n".join(text_parts)
        else:
            # CELL_BASED
            text_parts = []
            for row in data_rows:
                text_parts.append(
                    " | ".join(cell.strip() for cell in row if cell.strip())
                )
            full_text = "\n".join(text_parts)

        logger.debug(
            "Loaded CSV %s (%d rows, %d columns)",
            source_name,
            len(data_rows),
            len(headers),
        )
        return [
            LoadedDocument(
                content=full_text,
                source=source_name,
                mime_type="text/csv",
                metadata=DocumentMetadata(
                    word_count=self._count_words(full_text),
                    extra={
                        "row_count": len(data_rows),
                        "column_count": len(headers),
                        "headers": headers,
                    },
                ),
            )
        ]

    def supports_source(self, source: str) -> bool:
        """Return ``True`` if *source* ends with ``.csv``."""
        return source.lower().endswith(".csv")


__all__ = [
    "CSVLoadMode",
    "CSVLoader",
    "TabularConfig",
]
