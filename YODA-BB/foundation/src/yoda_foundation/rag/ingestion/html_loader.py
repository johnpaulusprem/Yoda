"""HTML document loader using BeautifulSoup."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from yoda_foundation.rag.ingestion.base_loader import (
    DocumentLoader,
    DocumentMetadata,
    LoadedDocument,
    LoaderConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class HTMLConfig(LoaderConfig):
    """HTML-specific loader configuration.

    Attributes:
        clean_html: Whether to remove boilerplate tags (script, nav, etc.).
        remove_navigation: Whether to strip ``<nav>``, ``<header>``, ``<footer>``.
        remove_scripts: Whether to strip ``<script>`` tags.
        remove_styles: Whether to strip ``<style>`` tags.
    """

    clean_html: bool = True
    remove_navigation: bool = True
    remove_scripts: bool = True
    remove_styles: bool = True


class HTMLLoader(DocumentLoader):
    """Load text content from HTML files or strings via BeautifulSoup.

    Strips boilerplate tags, extracts the ``<title>``, and converts the
    remaining HTML to plain text. Inline HTML strings (starting with ``<``)
    are accepted in addition to file paths and bytes.

    Args:
        config: HTML-specific configuration. Defaults to ``HTMLConfig()``.
    """

    REMOVE_TAGS: list[str] = ["script", "style", "nav", "header", "footer", "aside"]

    def __init__(self, config: HTMLConfig | None = None) -> None:
        super().__init__(config or HTMLConfig())

    @property
    def html_config(self) -> HTMLConfig:
        """Return the config cast to ``HTMLConfig``."""
        return self.config  # type: ignore[return-value]

    async def load(self, source: str | bytes) -> list[LoadedDocument]:
        """Load HTML from a file path, raw bytes, or an HTML string.

        When *source* is a ``str`` that starts with ``<`` or ``<!`` it is
        treated as inline HTML rather than a file path.
        """
        from bs4 import BeautifulSoup  # lazy import — heavy dependency

        if isinstance(source, str):
            if source.startswith("<") or source.startswith("<!"):
                html_content = source
                source_name = "html_string"
            else:
                try:
                    with open(source, "r", encoding=self.config.encoding) as f:
                        html_content = f.read()
                except Exception as exc:
                    logger.error("Failed to read HTML file %s: %s", source, exc)
                    raise
                source_name = source
        else:
            self._validate_size(source)
            html_content = source.decode(self.config.encoding)
            source_name = "bytes_input"

        soup = BeautifulSoup(html_content, "html.parser")

        # ---- Clean boilerplate tags -----------------------------------
        if self.html_config.clean_html:
            for tag_name in self.REMOVE_TAGS:
                for tag in soup.find_all(tag_name):
                    tag.decompose()

        # ---- Extract title --------------------------------------------
        title = ""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

        # ---- Extract body text ----------------------------------------
        text = soup.get_text(separator="\n", strip=True)
        # Collapse runs of 3+ blank lines into double newlines
        text = re.sub(r"\n{3,}", "\n\n", text)

        logger.debug("Loaded HTML %s (%d words)", source_name, self._count_words(text))
        return [
            LoadedDocument(
                content=text,
                source=source_name,
                mime_type="text/html",
                metadata=DocumentMetadata(
                    title=title,
                    word_count=self._count_words(text),
                ),
            )
        ]

    def supports_source(self, source: str) -> bool:
        """Return ``True`` if *source* ends with ``.html`` or ``.htm``."""
        return source.lower().endswith((".html", ".htm"))


__all__ = [
    "HTMLConfig",
    "HTMLLoader",
]
