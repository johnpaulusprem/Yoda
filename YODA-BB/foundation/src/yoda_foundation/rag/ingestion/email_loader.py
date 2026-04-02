"""Email (.eml) document loader using the stdlib email module."""

from __future__ import annotations

import email
import logging
import re
from dataclasses import dataclass
from email import policy
from typing import Any

from yoda_foundation.rag.ingestion.base_loader import (
    DocumentLoader,
    DocumentMetadata,
    LoadedDocument,
    LoaderConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class EmailConfig(LoaderConfig):
    """Email-specific loader configuration.

    Attributes:
        extract_attachments: Whether to process email attachments (not yet implemented).
        strip_signatures: Whether to remove email signatures from the body.
        max_attachment_size_mb: Maximum size for individual attachments in megabytes.
    """

    extract_attachments: bool = False
    strip_signatures: bool = True
    max_attachment_size_mb: float = 10.0


class EmailLoader(DocumentLoader):
    """Load text content from RFC-822 email messages (.eml files).

    Extracts headers (From, To, Subject, Date) and the plain-text body,
    falling back to HTML-to-text conversion when no ``text/plain`` part
    is available. Optionally strips common email signatures.

    Args:
        config: Email-specific configuration. Defaults to ``EmailConfig()``.
    """

    SIGNATURE_PATTERNS: list[str] = [
        r"\n--\s*\n",           # Standard sig separator
        r"\nSent from my ",     # Mobile signatures
        r"\nBest regards,",     # Common closings
        r"\nKind regards,",
        r"\nRegards,",
        r"\nThanks,",
    ]

    def __init__(self, config: EmailConfig | None = None) -> None:
        super().__init__(config or EmailConfig())

    @property
    def email_config(self) -> EmailConfig:
        """Return the config cast to ``EmailConfig``."""
        return self.config  # type: ignore[return-value]

    async def load(self, source: str | bytes) -> list[LoadedDocument]:
        """Load an email from a file path or raw bytes.

        The result includes email headers (From, To, Subject, Date) prepended
        to the extracted body text.
        """
        if isinstance(source, str):
            try:
                with open(source, "rb") as f:
                    data = f.read()
            except Exception as exc:
                logger.error("Failed to read email file %s: %s", source, exc)
                raise
            source_name = source
        else:
            data = source
            source_name = "bytes_input"

        self._validate_size(data)

        try:
            msg = email.message_from_bytes(data, policy=policy.default)
        except Exception as exc:
            logger.error("Failed to parse email from %s: %s", source_name, exc)
            raise

        # ---- Header fields --------------------------------------------
        subject = str(msg.get("subject", ""))
        from_addr = str(msg.get("from", ""))
        to_addr = str(msg.get("to", ""))
        date_str = str(msg.get("date", ""))

        # ---- Body extraction ------------------------------------------
        body = self._extract_body(msg)

        if self.email_config.strip_signatures:
            body = self._strip_signature(body)

        # ---- Assemble full content ------------------------------------
        content_parts = [
            f"From: {from_addr}",
            f"To: {to_addr}",
            f"Subject: {subject}",
            f"Date: {date_str}",
            "",
            body,
        ]
        full_text = "\n".join(content_parts)

        logger.debug("Loaded email %s (subject=%r)", source_name, subject)
        return [
            LoadedDocument(
                content=full_text,
                source=source_name,
                mime_type="message/rfc822",
                metadata=DocumentMetadata(
                    title=subject,
                    author=from_addr,
                    word_count=self._count_words(full_text),
                    extra={"to": to_addr, "date": date_str},
                ),
            )
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_body(self, msg: Any) -> str:
        """Extract the plain-text body from an email message.

        Falls back to HTML-to-text conversion via BeautifulSoup if no
        ``text/plain`` part is available.
        """
        if msg.is_multipart():
            # First pass: look for text/plain
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")

            # Second pass: fall back to text/html
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        from bs4 import BeautifulSoup  # lazy import

                        soup = BeautifulSoup(
                            payload.decode(charset, errors="replace"),
                            "html.parser",
                        )
                        return soup.get_text(separator="\n", strip=True)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")

        return ""

    def _strip_signature(self, text: str) -> str:
        """Remove the email signature by matching common separator patterns.

        Args:
            text: The email body text.

        Returns:
            The text with everything after the first signature separator removed.
        """
        for pattern in self.SIGNATURE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                return text[: match.start()].rstrip()
        return text

    def supports_source(self, source: str) -> bool:
        """Return ``True`` if *source* ends with ``.eml`` or ``.msg``."""
        return source.lower().endswith((".eml", ".msg"))


__all__ = [
    "EmailConfig",
    "EmailLoader",
]
