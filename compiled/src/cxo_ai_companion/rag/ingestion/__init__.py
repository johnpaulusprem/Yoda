"""Document format loaders for the RAG ingestion pipeline.

Supports PDF, DOCX, PPTX, HTML, CSV, and Email (.eml) formats.
Each loader implements the :class:`DocumentLoader` ABC and can operate
on both file paths and raw ``bytes`` input.
"""

from __future__ import annotations

from cxo_ai_companion.rag.ingestion.base_loader import (
    DocumentLoader,
    DocumentMetadata,
    LoadedDocument,
    LoaderConfig,
    LoadMode,
)
from cxo_ai_companion.rag.ingestion.csv_loader import (
    CSVLoader,
    TabularConfig,
)
from cxo_ai_companion.rag.ingestion.docx_loader import (
    DOCXConfig,
    DOCXLoader,
)
from cxo_ai_companion.rag.ingestion.email_loader import (
    EmailConfig,
    EmailLoader,
)
from cxo_ai_companion.rag.ingestion.html_loader import (
    HTMLConfig,
    HTMLLoader,
)
from cxo_ai_companion.rag.ingestion.pdf_loader import (
    PDFConfig,
    PDFLoader,
)
from cxo_ai_companion.rag.ingestion.pptx_loader import (
    PPTXConfig,
    PPTXLoader,
)

__all__ = [
    # Base types
    "DocumentLoader",
    "LoaderConfig",
    "LoadMode",
    "DocumentMetadata",
    "LoadedDocument",
    # PDF
    "PDFLoader",
    "PDFConfig",
    # DOCX
    "DOCXLoader",
    "DOCXConfig",
    # PPTX
    "PPTXLoader",
    "PPTXConfig",
    # HTML
    "HTMLLoader",
    "HTMLConfig",
    # CSV
    "CSVLoader",
    "TabularConfig",
    # Email
    "EmailLoader",
    "EmailConfig",
]
