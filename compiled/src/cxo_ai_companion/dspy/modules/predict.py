"""DSPy Predict module — the basic building block for structured LLM calls."""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from cxo_ai_companion.dspy.adapters.llm_adapter import BaseLLMAdapter
from cxo_ai_companion.dspy.signatures.base_signature import Signature
from cxo_ai_companion.exceptions.dspy import ProgramExecutionError
from cxo_ai_companion.security.context import SecurityContext

logger = logging.getLogger(__name__)


@dataclass
class PredictConfig:
    """Configuration for Predict modules.

    Attributes:
        temperature: Sampling temperature for the LLM call.
        max_tokens: Maximum output tokens per call.
        model: Model deployment name to use.
        n: Number of completions to generate per call.
        cache_enabled: Whether to enable response caching.
        retry_count: Number of retry attempts on failure.
    """

    temperature: float = 0.1
    max_tokens: int = 4096
    model: str = "gpt-4o-mini"
    n: int = 1
    cache_enabled: bool = False
    retry_count: int = 3


@dataclass
class PredictResult:
    """Result from a Predict module execution.

    Attributes:
        outputs: Parsed and validated output fields from the LLM response.
        raw_response: The unprocessed text returned by the LLM.
        input_tokens: Estimated input token count.
        output_tokens: Estimated output token count.
        latency_ms: Round-trip latency in milliseconds.
        prediction_id: Short unique identifier for this prediction.
    """

    outputs: dict[str, Any]
    raw_response: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    prediction_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


class BaseDSPyModule(ABC):
    """Abstract base class for all DSPy modules.

    Provides signature-based prompt formatting, few-shot demo management,
    and an abstract :meth:`forward` method that subclasses implement.

    Args:
        signature: The Signature class defining input/output fields.
        adapter: The LLM adapter used to execute prompts.
        config: Module configuration. Defaults to ``PredictConfig()``.
    """

    def __init__(
        self,
        signature: type[Signature],
        adapter: BaseLLMAdapter,
        config: PredictConfig | None = None,
    ) -> None:
        self._signature = signature
        self._adapter = adapter
        self._config = config or PredictConfig()
        self._demos: list[dict[str, str]] = []

    @property
    def signature(self) -> type[Signature]:
        return self._signature

    @property
    def config(self) -> PredictConfig:
        return self._config

    @abstractmethod
    async def forward(
        self,
        security_context: SecurityContext | None = None,
        **kwargs: Any,
    ) -> PredictResult:
        """Execute the module and return a structured result.

        Args:
            security_context: Optional security context for authorization.
            **kwargs: Input field values matching the signature.

        Returns:
            A :class:`PredictResult` with parsed outputs and metadata.
        """
        ...

    def set_demos(self, demos: list[dict[str, str]]) -> None:
        """Replace all few-shot demonstrations.

        Args:
            demos: List of demo dictionaries mapping field names to values.
        """
        self._demos = list(demos)

    def add_demo(self, demo: dict[str, str]) -> None:
        """Add a single few-shot demonstration.

        Args:
            demo: A dictionary mapping field names to example values.
        """
        self._demos.append(demo)

    def clear_demos(self) -> None:
        """Remove all few-shot demonstrations."""
        self._demos.clear()

    def _format_demos(self) -> str:
        """Format few-shot demonstrations for inclusion in the prompt.

        Returns:
            A formatted string with all demos, or empty string if none exist.
        """
        if not self._demos:
            return ""

        parts: list[str] = []
        for demo in self._demos:
            lines = ["---", "Input:"]
            for key, value in demo.items():
                # Separate inputs from outputs by checking signature fields
                if key in self._signature.get_input_fields():
                    lines.append(f"{key}: {value}")
            lines.append("Output:")
            for key, value in demo.items():
                if key in self._signature.get_output_fields():
                    lines.append(f"{key}: {value}")
            lines.append("---")
            parts.append("\n".join(lines))

        return "\n\n".join(parts)


class Predict(BaseDSPyModule):
    """Basic DSPy module: validate inputs, format prompt, call LLM, parse outputs.

    This is the simplest module -- it formats the signature into a prompt,
    calls the LLM adapter, and parses the response into validated outputs.
    """

    async def forward(
        self,
        security_context: SecurityContext | None = None,
        **kwargs: Any,
    ) -> PredictResult:
        """Execute a Predict call.

        Steps:
        1. Validate inputs against the signature.
        2. Format the prompt from the signature.
        3. Prepend few-shot demos if available.
        4. Call the LLM adapter.
        5. Parse and validate outputs.
        6. Return a PredictResult.
        """
        try:
            validated_inputs = self._signature.validate_inputs(**kwargs)
            prompt = self._signature.format_prompt(**validated_inputs)

            # Prepend demos if any
            demos_text = self._format_demos()
            if demos_text:
                prompt = f"{demos_text}\n\n{prompt}"

            response = await self._adapter.call(
                prompt,
                security_context,
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                model=self._config.model,
            )

            outputs = self._signature.parse_output(response.text)
            validated_outputs = self._signature.validate_outputs(outputs)

            logger.debug(
                "Predict completed: signature=%s, latency=%.1fms",
                self._signature.__name__,
                response.latency_ms,
            )

            return PredictResult(
                outputs=validated_outputs,
                raw_response=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=response.latency_ms,
            )
        except ProgramExecutionError:
            raise
        except Exception as exc:
            raise ProgramExecutionError(
                message=(
                    f"Predict execution failed for "
                    f"{self._signature.__name__}: {exc}"
                ),
                cause=exc if isinstance(exc, Exception) else None,
            ) from exc


__all__ = [
    "PredictConfig",
    "PredictResult",
    "BaseDSPyModule",
    "Predict",
]
