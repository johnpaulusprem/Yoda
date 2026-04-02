"""
Model fallback for LLM resilience.

Provides automatic fallback to alternative models when primary fails.

Example:
    ```python
    from yoda_foundation.resilience.fallback import ModelFallback

    fallback = ModelFallback(
        primary_model="gpt-4",
        fallback_models=["gpt-3.5-turbo", "claude-2"],
    )

    result = await fallback.generate(
        prompt="Hello",
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from yoda_foundation.exceptions import FallbackFailedError
from yoda_foundation.exceptions.base import AgenticBaseException
from yoda_foundation.security.context import SecurityContext


logger = logging.getLogger(__name__)


class ModelFallback:
    """
    Automatic model fallback.

    Falls back to alternative models when primary fails.

    Attributes:
        primary_model: Name of the primary model to use.
        fallback_models: List of fallback model names in order.
        generator_func: Function to generate text with a model.

    Example:
        ```python
        fallback = ModelFallback(
            primary_model="gpt-4",
            fallback_models=["gpt-3.5-turbo"],
        )

        result = await fallback.generate(
            prompt="Test",
            security_context=context,
        )
        ```
    """

    def __init__(
        self,
        primary_model: str,
        fallback_models: list[str],
        generator_func: Callable[[str, str, dict[str, Any]], Awaitable[str]] | None = None,
    ) -> None:
        """
        Initialize model fallback.

        Args:
            primary_model: Primary model name
            fallback_models: List of fallback model names
            generator_func: Custom generation function
        """
        self.primary_model = primary_model
        self.fallback_models = fallback_models
        self.generator_func = generator_func or self._default_generator

    async def generate(
        self,
        prompt: str,
        security_context: SecurityContext,
        **model_kwargs: Any,
    ) -> str:
        """
        Generate with automatic fallback.

        Args:
            prompt: Input prompt
            security_context: Security context
            **model_kwargs: Model parameters

        Returns:
            Generated text

        Raises:
            FallbackFailedError: If all models fail
        """
        models = [self.primary_model] + self.fallback_models
        errors: list[Exception] = []

        for model in models:
            try:
                logger.info(f"Attempting generation with model: {model}")
                result = await self.generator_func(prompt, model, model_kwargs)
                return result

            except (
                AgenticBaseException,
                ConnectionError,
                TimeoutError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
                RuntimeError,
            ) as e:
                logger.warning(f"Model {model} failed: {e!s}")
                errors.append(e)

        raise FallbackFailedError(
            operation="model_generation",
            fallback_chain=models,
            errors=errors,
        )

    async def _default_generator(
        self,
        prompt: str,
        model: str,
        kwargs: dict[str, Any],
    ) -> str:
        """
        Default generator placeholder for model generation.

        This is a placeholder implementation that should be replaced
        with actual LLM API calls in production.

        Args:
            prompt: The input prompt to generate from.
            model: The model name to use for generation.
            kwargs: Additional keyword arguments for the model.

        Returns:
            Generated text response from the model.
        """
        # In production, call actual LLM API
        return f"Response from {model}"
