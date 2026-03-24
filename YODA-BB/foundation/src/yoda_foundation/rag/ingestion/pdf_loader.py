"""PDF document loader using PyPDF2."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoda_foundation.rag.ingestion.base_loader import (
    DocumentLoader,
    DocumentMetadata,
    LoadedDocument,
    LoaderConfig,
    LoadMode,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class PDFConfig(LoaderConfig):
    """PDF-specific loader configuration.

    Attributes:
        extract_tables: Whether to attempt table extraction (not yet implemented).
        page_range: Optional ``(start, end)`` 0-indexed page range to extract.
        ocr_enabled: Whether to enable OCR for scanned pages (not yet implemented).
    """

    extract_tables: bool = False
    page_range: tuple[int, int] | None = None  # (start, end) 0-indexed
    ocr_enabled: bool = False


class PDFLoader(DocumentLoader):
    """Load text content from PDF files via PyPDF2.

    Supports ``SINGLE`` mode (all pages concatenated) and ``PAGE`` mode
    (one ``LoadedDocument`` per non-empty page).

    Args:
        config: PDF-specific configuration. Defaults to ``PDFConfig()``.
    """

    def __init__(self, config: PDFConfig | None = None) -> None:
        super().__init__(config or PDFConfig())

    @property
    def pdf_config(self) -> PDFConfig:
        """Return the config cast to ``PDFConfig``."""
        return self.config  # type: ignore[return-value]

    async def load(self, source: str | bytes) -> list[LoadedDocument]:
        """Load a PDF from a file path or raw bytes.

        In ``PAGE`` mode each non-empty page becomes a separate
        :class:`LoadedDocument`.  In ``SINGLE`` mode (the default) all
        pages are concatenated into one document.
        """
        import PyPDF2  # lazy import — heavy dependency

        if isinstance(source, str):
            with open(source, "rb") as f:
                data = f.read()
            source_name = source
        else:
            data = source
            source_name = "bytes_input"

        self._validate_size(data)

        try:
            reader = PyPDF2.PdfReader(io.BytesIO(data))
        except Exception as exc:
            logger.error("Failed to parse PDF from %s: %s", source_name, exc)
            raise

        # ---- Metadata --------------------------------------------------
        metadata = DocumentMetadata()
        if self.pdf_config.extract_metadata and reader.metadata:
            metadata = DocumentMetadata(
                title=str(reader.metadata.title or ""),
                author=str(reader.metadata.author or ""),
                page_count=len(reader.pages),
            )
        else:
            metadata.page_count = len(reader.pages)

        # ---- Page range ------------------------------------------------
        start = 0
        end = len(reader.pages)
        if self.pdf_config.page_range:
            start, end = self.pdf_config.page_range
            end = min(end, len(reader.pages))

        # ---- Extract text per mode ------------------------------------
        if self.pdf_config.mode == LoadMode.PAGE:
            documents: list[LoadedDocument] = []
            for i in range(start, end):
                text = reader.pages[i].extract_text() or ""
                if text.strip():
                    page_meta = DocumentMetadata(
                        title=metadata.title,
                        author=metadata.author,
                        page_count=metadata.page_count,
                        word_count=self._count_words(text),
                    )
                    documents.append(
                        LoadedDocument(
                            content=text,
                            source=source_name,
                            mime_type="application/pdf",
                            metadata=page_meta,
                            page_number=i + 1,
                        )
                    )
            logger.debug("Loaded %d pages from PDF %s", len(documents), source_name)
            return documents

        # SINGLE mode — concatenate all pages
        all_text: list[str] = []
        for i in range(start, end):
            text = reader.pages[i].extract_text() or ""
            if text.strip():
                all_text.append(text)

        full_text = "\n\n".join(all_text)
        metadata.word_count = self._count_words(full_text)

        logger.debug("Loaded PDF %s as single document (%d words)", source_name, metadata.word_count)
        return [
            LoadedDocument(
                content=full_text,
                source=source_name,
                mime_type="application/pdf",
                metadata=metadata,
            )
        ]

    def supports_source(self, source: str) -> bool:
        """Return ``True`` if *source* ends with ``.pdf``."""
        return source.lower().endswith(".pdf")


__all__ = [
    "PDFConfig",
    "PDFLoader",
]
