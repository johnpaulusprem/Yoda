"""DSPy Chain-of-Thought module — prompts the LLM to reason step-by-step."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from cxo_ai_companion.dspy.adapters.llm_adapter import BaseLLMAdapter
from cxo_ai_companion.dspy.modules.predict import (
    BaseDSPyModule,
    PredictConfig,
    PredictResult,
)
from cxo_ai_companion.dspy.signatures.base_signature import Signature
from cxo_ai_companion.exceptions.dspy import ProgramExecutionError
from cxo_ai_companion.security.context import SecurityContext

logger = logging.getLogger(__name__)


@dataclass
class ChainOfThoughtConfig(PredictConfig):
    """Extended configuration for Chain-of-Thought modules.

    Attributes:
        require_rationale: Whether to require a rationale section in the output.
        max_reasoning_steps: Maximum number of reasoning steps to extract.
        step_by_step_prompt: Instruction prepended to the prompt to elicit reasoning.
        rationale_prefix: Label placed before the base prompt to capture reasoning.
    """

    require_rationale: bool = True
    max_reasoning_steps: int = 10
    step_by_step_prompt: str = "Let's think step by step."
    rationale_prefix: str = "Reasoning:"


@dataclass
class ChainOfThoughtResult(PredictResult):
    """Extended result that includes step-by-step reasoning information.

    Attributes:
        rationale: Free-text reasoning extracted before the output fields.
        reasoning_steps: Individual steps parsed from the rationale.
        num_steps: Count of reasoning steps extracted.
        confidence: Optional confidence score (0.0 to 1.0) from the outputs.
    """

    rationale: str = ""
    reasoning_steps: list[str] = field(default_factory=list)
    num_steps: int = 0
    confidence: float | None = None


class ChainOfThought(BaseDSPyModule):
    """DSPy module that injects step-by-step reasoning before output.

    Prepends a reasoning prompt to encourage the LLM to show its work,
    then extracts the rationale and reasoning steps from the response.

    Args:
        signature: The Signature class defining input/output fields.
        adapter: The LLM adapter used to execute prompts.
        config: Chain-of-Thought configuration. Defaults to
            ``ChainOfThoughtConfig()``.
    """

    def __init__(
        self,
        signature: type[Signature],
        adapter: BaseLLMAdapter,
        config: ChainOfThoughtConfig | None = None,
    ) -> None:
        effective_config = config or ChainOfThoughtConfig()
        super().__init__(signature, adapter, effective_config)
        self._cot_config = effective_config

    async def forward(
        self,
        security_context: SecurityContext | None = None,
        **kwargs: Any,
    ) -> ChainOfThoughtResult:
        """Execute a Chain-of-Thought call.

        Steps:
        1. Validate inputs against the signature.
        2. Format the base prompt from the signature.
        3. Prepend step-by-step instruction and rationale prefix.
        4. Prepend few-shot demos if available.
        5. Call the LLM adapter.
        6. Extract rationale (text before the first output field).
        7. Parse reasoning steps from the rationale.
        8. Parse and validate outputs.
        9. Extract confidence if present in outputs.
        10. Return a ChainOfThoughtResult.
        """
        try:
            validated_inputs = self._signature.validate_inputs(**kwargs)
            base_prompt = self._signature.format_prompt(**validated_inputs)

            # Build CoT prompt: step_by_step instruction + rationale prefix + base
            cot_prompt = (
                f"{self._cot_config.step_by_step_prompt}\n\n"
                f"{self._cot_config.rationale_prefix}\n\n"
                f"{base_prompt}"
            )

            # Prepend demos if any
            demos_text = self._format_demos()
            if demos_text:
                cot_prompt = f"{demos_text}\n\n{cot_prompt}"

            response = await self._adapter.call(
                cot_prompt,
                security_context,
                temperature=self._cot_config.temperature,
                max_tokens=self._cot_config.max_tokens,
                model=self._cot_config.model,
            )

            # Extract rationale: everything before the first output field
            rationale = self._extract_rationale(response.text)

            # Parse reasoning steps from the rationale
            reasoning_steps = self._parse_reasoning_steps(rationale)

            # Parse structured outputs
            outputs = self._signature.parse_output(response.text)
            validated_outputs = self._signature.validate_outputs(outputs)

            # Extract confidence from outputs if present
            confidence = self._extract_confidence(validated_outputs)

            logger.debug(
                "ChainOfThought completed: signature=%s, "
                "steps=%d, latency=%.1fms",
                self._signature.__name__,
                len(reasoning_steps),
                response.latency_ms,
            )

            return ChainOfThoughtResult(
                outputs=validated_outputs,
                raw_response=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                latency_ms=response.latency_ms,
                rationale=rationale,
                reasoning_steps=reasoning_steps,
                num_steps=len(reasoning_steps),
                confidence=confidence,
            )
        except ProgramExecutionError:
            raise
        except Exception as exc:
            raise ProgramExecutionError(
                message=(
                    f"ChainOfThought execution failed for "
                    f"{self._signature.__name__}: {exc}"
                ),
                cause=exc if isinstance(exc, Exception) else None,
            ) from exc

    def _extract_rationale(self, text: str) -> str:
        """Extract reasoning text that appears before the first output field.

        Args:
            text: The full LLM response text.

        Returns:
            The rationale portion of the response, stripped of leading/trailing whitespace.
        """
        output_field_names = set(self._signature.get_output_fields().keys())
        lines = text.split("\n")
        rationale_lines: list[str] = []

        for line in lines:
            # Check if this line starts an output field
            is_output_field = False
            for fname in output_field_names:
                if line.lower().startswith(f"{fname.lower()}:"):
                    is_output_field = True
                    break

            if is_output_field:
                break

            rationale_lines.append(line)

        return "\n".join(rationale_lines).strip()

    def _parse_reasoning_steps(self, rationale: str) -> list[str]:
        """Parse individual reasoning steps from the rationale text.

        Recognises lines starting with ``-``, a bullet, ``Step``, or
        a leading digit as distinct reasoning steps. Results are capped
        at ``max_reasoning_steps``.

        Args:
            rationale: The extracted rationale text.

        Returns:
            A list of reasoning step strings.
        """
        steps: list[str] = []
        for line in rationale.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if (
                stripped.startswith("-")
                or stripped.startswith("\u2022")  # bullet
                or stripped.lower().startswith("step")
                or (len(stripped) > 0 and stripped[0].isdigit())
            ):
                steps.append(stripped)

        # Respect max_reasoning_steps
        max_steps = self._cot_config.max_reasoning_steps
        return steps[:max_steps]

    @staticmethod
    def _extract_confidence(outputs: dict[str, Any]) -> float | None:
        """Try to parse a confidence score from the outputs.

        Args:
            outputs: Validated output dictionary from the signature.

        Returns:
            A float clamped to ``[0.0, 1.0]``, or ``None`` if not parseable.
        """
        confidence_raw = outputs.get("confidence")
        if confidence_raw is None:
            return None

        try:
            value = float(str(confidence_raw).strip())
            # Clamp to [0.0, 1.0]
            return max(0.0, min(1.0, value))
        except (ValueError, TypeError):
            return None


__all__ = [
    "ChainOfThoughtConfig",
    "ChainOfThoughtResult",
    "ChainOfThought",
]
