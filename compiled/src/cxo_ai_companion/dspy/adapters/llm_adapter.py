"""LLM adapter layer wrapping AIFoundryConnector for DSPy modules.

Provides ``LLMAdapter`` for direct calls and ``CachedLLMAdapter`` for
in-memory caching with TTL-based expiration.
"""

from __future__ import annotations

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from cxo_ai_companion.data_access.connectors.ai_foundry_connector import (
    AIFoundryConnector,
)
from cxo_ai_companion.exceptions.dspy import ProgramExecutionError
from cxo_ai_companion.security.context import SecurityContext
from cxo_ai_companion.utilities.caching.cache import CacheInterface

logger = logging.getLogger(__name__)


@dataclass
class AdapterConfig:
    """Configuration for LLM adapters.

    Attributes:
        default_temperature: Sampling temperature when not overridden per call.
        max_tokens: Maximum output tokens per LLM call.
        default_model: Model deployment name when not overridden per call.
        cache_enabled: Whether to enable in-memory response caching.
        cache_ttl_seconds: Time-to-live for cached responses in seconds.
        retry_count: Number of retry attempts on transient failures.
    """

    default_temperature: float = 0.1
    max_tokens: int = 4096
    default_model: str = "gpt-4o-mini"
    cache_enabled: bool = False
    cache_ttl_seconds: int = 3600
    retry_count: int = 3


@dataclass
class AdapterResponse:
    """Response from an LLM adapter call.

    Attributes:
        text: The generated text from the LLM.
        input_tokens: Estimated input token count.
        output_tokens: Estimated output token count.
        model: Model deployment name that served the request.
        latency_ms: Round-trip latency in milliseconds.
        cached: Whether this response was served from cache.
        metadata: Additional metadata (temperature, cache key, etc.).
    """

    text: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: float
    cached: bool
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseLLMAdapter(ABC):
    """Abstract base class for LLM adapters.

    Subclasses must implement :meth:`call` to send a prompt to an LLM
    and return a structured :class:`AdapterResponse`.
    """

    @abstractmethod
    async def call(
        self,
        prompt: str,
        security_context: SecurityContext | None = None,
        **kwargs: Any,
    ) -> AdapterResponse:
        """Send a prompt to the LLM and return a structured response.

        Args:
            prompt: The user prompt text.
            security_context: Optional security context for audit logging.
            **kwargs: Provider-specific overrides (temperature, model, etc.).

        Returns:
            An :class:`AdapterResponse` with the generated text and metadata.
        """
        ...


@dataclass
class _CacheEntry:
    """Internal cache entry with expiration tracking.

    Attributes:
        response: The cached adapter response.
        created_at: Monotonic timestamp when the entry was created.
        ttl_seconds: Time-to-live in seconds before the entry expires.
    """

    response: AdapterResponse
    created_at: float
    ttl_seconds: int

    @property
    def is_expired(self) -> bool:
        """Return ``True`` if the entry has exceeded its TTL."""
        return (time.monotonic() - self.created_at) >= self.ttl_seconds


class LLMAdapter(BaseLLMAdapter):
    """LLM adapter that wraps an AIFoundryConnector.

    Builds a messages list with system and user roles, calls the
    connector's ``complete()`` method, and tracks latency.

    Args:
        connector: The AI Foundry connector for making LLM calls.
        config: Adapter configuration. Defaults to ``AdapterConfig()``.
    """

    def __init__(
        self,
        connector: AIFoundryConnector,
        config: AdapterConfig | None = None,
    ) -> None:
        self._connector = connector
        self._config = config or AdapterConfig()

    @property
    def config(self) -> AdapterConfig:
        return self._config

    async def call(
        self,
        prompt: str,
        security_context: SecurityContext | None = None,
        **kwargs: Any,
    ) -> AdapterResponse:
        """Call the LLM via AIFoundryConnector.

        Args:
            prompt: The user prompt text.
            security_context: Optional security context (logged but not
                enforced here).
            **kwargs: Overrides for ``temperature``, ``max_tokens``,
                ``model``, and ``system_prompt``.

        Returns:
            An :class:`AdapterResponse` with generated text and timing.

        Raises:
            ProgramExecutionError: If the LLM call fails.
        """
        model = kwargs.get("model", self._config.default_model)
        temperature = kwargs.get("temperature", self._config.default_temperature)
        system_prompt = kwargs.get(
            "system_prompt",
            "You are a helpful AI assistant. Follow instructions precisely.",
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        if security_context is not None:
            logger.debug(
                "LLMAdapter call for user=%s, model=%s",
                security_context.user_id,
                model,
            )

        start = time.perf_counter()
        try:
            response_text = await self._connector.complete(
                model=model,
                messages=messages,
                temperature=temperature,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "LLM call failed after %.1fms: %s",
                elapsed_ms,
                exc,
            )
            raise ProgramExecutionError(
                message=f"LLM call failed: {exc}",
                cause=exc if isinstance(exc, Exception) else None,
                details={"model": model, "latency_ms": elapsed_ms},
            ) from exc

        elapsed_ms = (time.perf_counter() - start) * 1000

        # The AIFoundryConnector.complete() returns a plain string.
        # Token counts are not directly available from the connector;
        # estimate from character lengths as a reasonable fallback.
        input_tokens = len(prompt) // 4
        output_tokens = len(response_text) // 4

        logger.debug(
            "LLM call completed in %.1fms, model=%s, "
            "est_input_tokens=%d, est_output_tokens=%d",
            elapsed_ms,
            model,
            input_tokens,
            output_tokens,
        )

        return AdapterResponse(
            text=response_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            latency_ms=elapsed_ms,
            cached=False,
            metadata={
                "temperature": temperature,
                "system_prompt_length": len(system_prompt),
            },
        )


class CachedLLMAdapter(LLMAdapter):
    """LLM adapter with in-memory caching and TTL expiration.

    Cache key is derived from a SHA-256 hash of (prompt, model, temperature).
    On cache hit the stored ``AdapterResponse`` is returned with
    ``cached=True`` and zero latency.

    Args:
        connector: The AI Foundry connector for making LLM calls.
        config: Adapter configuration. Defaults to ``AdapterConfig(cache_enabled=True)``.
    """

    def __init__(
        self,
        connector: AIFoundryConnector,
        config: AdapterConfig | None = None,
        external_cache: CacheInterface | None = None,
    ) -> None:
        effective_config = config or AdapterConfig(cache_enabled=True)
        super().__init__(connector, effective_config)
        self._cache: dict[str, _CacheEntry] = {}
        self._external_cache = external_cache
        self._cache_hits: int = 0
        self._cache_misses: int = 0

    @staticmethod
    def _make_cache_key(prompt: str, model: str, temperature: float) -> str:
        """Create a deterministic cache key."""
        raw = f"{prompt}|{model}|{temperature}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def call(
        self,
        prompt: str,
        security_context: SecurityContext | None = None,
        **kwargs: Any,
    ) -> AdapterResponse:
        model = kwargs.get("model", self._config.default_model)
        temperature = kwargs.get("temperature", self._config.default_temperature)

        cache_key = self._make_cache_key(prompt, model, temperature)

        # Try external cache (Redis) first
        if self._external_cache is not None:
            try:
                cached_data = await self._external_cache.get(f"llm:{cache_key}")
                if cached_data is not None:
                    self._cache_hits += 1
                    logger.debug("External cache hit for key=%s", cache_key[:12])
                    return AdapterResponse(
                        text=cached_data["text"],
                        input_tokens=cached_data["input_tokens"],
                        output_tokens=cached_data["output_tokens"],
                        model=cached_data["model"],
                        latency_ms=0.0,
                        cached=True,
                        metadata={**cached_data.get("metadata", {}), "cache_key": cache_key[:12]},
                    )
            except Exception:
                logger.debug("External cache get failed, falling back to in-memory")

        # Fall back to in-memory cache
        entry = self._cache.get(cache_key)
        if entry is not None and not entry.is_expired:
            self._cache_hits += 1
            logger.debug("Cache hit for key=%s", cache_key[:12])
            cached_response = entry.response
            return AdapterResponse(
                text=cached_response.text,
                input_tokens=cached_response.input_tokens,
                output_tokens=cached_response.output_tokens,
                model=cached_response.model,
                latency_ms=0.0,
                cached=True,
                metadata={**cached_response.metadata, "cache_key": cache_key[:12]},
            )

        # Evict expired entry if present
        if entry is not None and entry.is_expired:
            del self._cache[cache_key]

        # Cache miss — call parent
        self._cache_misses += 1
        response = await super().call(prompt, security_context, **kwargs)

        # Store in in-memory cache
        self._cache[cache_key] = _CacheEntry(
            response=response,
            created_at=time.monotonic(),
            ttl_seconds=self._config.cache_ttl_seconds,
        )

        # Store in external cache (Redis)
        if self._external_cache is not None:
            try:
                await self._external_cache.set(
                    f"llm:{cache_key}",
                    {
                        "text": response.text,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "model": response.model,
                        "metadata": response.metadata,
                    },
                    ttl_seconds=self._config.cache_ttl_seconds,
                )
            except Exception:
                logger.debug("External cache set failed, continuing without caching")

        return response

    def clear_cache(self) -> None:
        """Remove all entries from the cache."""
        self._cache.clear()
        logger.debug("LLM adapter cache cleared.")

    def cache_stats(self) -> dict[str, Any]:
        """Return cache statistics including hit rate and entry counts.

        Returns:
            A dictionary with keys ``total_entries``, ``active_entries``,
            ``expired_entries``, ``hits``, ``misses``, and ``hit_rate``.
        """
        # Count non-expired entries
        active = sum(1 for e in self._cache.values() if not e.is_expired)
        expired = len(self._cache) - active
        return {
            "total_entries": len(self._cache),
            "active_entries": active,
            "expired_entries": expired,
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "hit_rate": (
                self._cache_hits / (self._cache_hits + self._cache_misses)
                if (self._cache_hits + self._cache_misses) > 0
                else 0.0
            ),
        }


__all__ = [
    "AdapterConfig",
    "AdapterResponse",
    "BaseLLMAdapter",
    "LLMAdapter",
    "CachedLLMAdapter",
]
