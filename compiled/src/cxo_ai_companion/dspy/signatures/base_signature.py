"""
Core DSPy signature system with metaclass-based field discovery.

Signatures define the input/output contract for LLM calls, enabling
structured prompting, automatic prompt formatting, and output parsing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from cxo_ai_companion.exceptions.dspy import SignatureError

logger = logging.getLogger(__name__)


@dataclass
class SignatureField:
    """Describes a single input or output field within a Signature.

    Attributes:
        name: Field name (populated by :class:`SignatureMeta` from the class attribute).
        description: Human-readable description used in prompt generation.
        prefix: Optional label prefix for the prompt (defaults to field name).
        type_hint: Python type used for prompt formatting context.
        required: Whether the field must be supplied (input) or produced (output).
        default: Default value when the field is not required.
    """

    name: str
    description: str
    prefix: str
    type_hint: type
    required: bool
    default: Any
    _is_input: bool = field(default=True, repr=False)


def InputField(
    description: str,
    prefix: str = "",
    type_hint: type = str,
    required: bool = True,
    default: Any = None,
) -> SignatureField:
    """Construct a ``SignatureField`` marked as an input field.

    Args:
        description: Human-readable description for prompt generation.
        prefix: Optional label prefix in the formatted prompt.
        type_hint: Python type for prompt context.
        required: Whether this input is mandatory.
        default: Default value when not required.

    Returns:
        A ``SignatureField`` with ``_is_input=True``.
    """
    return SignatureField(
        name="",  # filled in by SignatureMeta
        description=description,
        prefix=prefix,
        type_hint=type_hint,
        required=required,
        default=default,
        _is_input=True,
    )


def OutputField(
    description: str,
    prefix: str = "",
    type_hint: type = str,
    required: bool = True,
    default: Any = None,
) -> SignatureField:
    """Construct a ``SignatureField`` marked as an output field.

    Args:
        description: Human-readable description for prompt generation.
        prefix: Optional label prefix in the formatted prompt.
        type_hint: Python type for prompt context.
        required: Whether this output is mandatory.
        default: Default value when not required.

    Returns:
        A ``SignatureField`` with ``_is_input=False``.
    """
    return SignatureField(
        name="",  # filled in by SignatureMeta
        description=description,
        prefix=prefix,
        type_hint=type_hint,
        required=required,
        default=default,
        _is_input=False,
    )


class SignatureMeta(type):
    """Metaclass that discovers SignatureField instances on class creation.

    Scans the class namespace for ``SignatureField`` objects, assigns their
    ``name`` attribute from the class-level variable name, and separates
    them into ``_input_fields`` and ``_output_fields`` dictionaries.
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> SignatureMeta:
        input_fields: dict[str, SignatureField] = {}
        output_fields: dict[str, SignatureField] = {}

        # Inherit fields from base classes
        for base in bases:
            if hasattr(base, "_input_fields"):
                input_fields.update(base._input_fields)  # type: ignore[attr-defined]
            if hasattr(base, "_output_fields"):
                output_fields.update(base._output_fields)  # type: ignore[attr-defined]

        # Scan the current class namespace for SignatureField instances
        for attr_name, attr_value in namespace.items():
            if isinstance(attr_value, SignatureField):
                # Set the field name from the attribute name
                attr_value.name = attr_name
                if attr_value._is_input:
                    input_fields[attr_name] = attr_value
                else:
                    output_fields[attr_name] = attr_value

        namespace["_input_fields"] = input_fields
        namespace["_output_fields"] = output_fields

        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        return cls


class Signature(metaclass=SignatureMeta):
    """Base class for all DSPy signatures.

    Subclasses declare input and output fields as class-level attributes
    using ``InputField(...)`` and ``OutputField(...)``.  The metaclass
    automatically collects them, and the classmethods below provide prompt
    formatting, output parsing, and validation.
    """

    _input_fields: dict[str, SignatureField]
    _output_fields: dict[str, SignatureField]

    @classmethod
    def get_input_fields(cls) -> dict[str, SignatureField]:
        """Return a mapping of input field names to their specs."""
        return dict(cls._input_fields)

    @classmethod
    def get_output_fields(cls) -> dict[str, SignatureField]:
        """Return a mapping of output field names to their specs."""
        return dict(cls._output_fields)

    @classmethod
    def format_prompt(cls, **inputs: Any) -> str:
        """Build a structured prompt from input field values.

        The prompt describes the expected inputs and outputs, then
        provides the actual input values, and finally instructs the
        LLM to respond with labelled output fields.

        Args:
            **inputs: Keyword arguments mapping input field names to values.

        Returns:
            A fully formatted prompt string ready for LLM consumption.
        """
        # --- describe inputs ---
        input_descriptions: list[str] = []
        for field_name, field_spec in cls._input_fields.items():
            input_descriptions.append(
                f"`{field_name}` ({field_spec.type_hint.__name__}): {field_spec.description}"
            )

        # --- describe outputs ---
        output_descriptions: list[str] = []
        for field_name, field_spec in cls._output_fields.items():
            output_descriptions.append(
                f"`{field_name}` ({field_spec.type_hint.__name__}): {field_spec.description}"
            )

        # --- provide input values ---
        input_values: list[str] = []
        for field_name in cls._input_fields:
            value = inputs.get(field_name, "")
            prefix = cls._input_fields[field_name].prefix
            label = prefix if prefix else field_name
            input_values.append(f"{label}: {value}")

        # --- assemble ---
        doc = cls.__doc__ or "Follow the instructions below."
        parts = [
            doc.strip(),
            "",
            f"Given the fields: {', '.join(input_descriptions)}",
            "",
            f"Produce the fields: {', '.join(output_descriptions)}",
            "",
            "---",
            "",
        ]
        parts.extend(input_values)
        parts.append("")
        parts.append(
            "Respond with each output field on its own line, "
            "prefixed with the field name and a colon."
        )

        return "\n".join(parts)

    @classmethod
    def parse_output(cls, text: str) -> dict[str, Any]:
        """Parse LLM output text into a dictionary keyed by output field name.

        Recognises ``field_name: value`` patterns and accumulates multiline
        values until the next recognised field header.

        Args:
            text: Raw text response from the LLM.

        Returns:
            A dictionary mapping output field names to their parsed values.
        """
        output_field_names = set(cls._output_fields.keys())
        result: dict[str, Any] = {}
        current_field: str | None = None
        current_lines: list[str] = []

        for line in text.split("\n"):
            # Check whether this line starts a new output field
            matched_field: str | None = None
            for fname in output_field_names:
                # Accept "field_name:" at the start of a line (case-insensitive)
                if line.lower().startswith(f"{fname.lower()}:"):
                    matched_field = fname
                    break

            if matched_field is not None:
                # Flush the previous field
                if current_field is not None:
                    result[current_field] = "\n".join(current_lines).strip()

                current_field = matched_field
                # Value is everything after "field_name:"
                _, _, rest = line.partition(":")
                current_lines = [rest.strip()]
            elif current_field is not None:
                current_lines.append(line)

        # Flush last field
        if current_field is not None:
            result[current_field] = "\n".join(current_lines).strip()

        return result

    @classmethod
    def validate_inputs(cls, **kwargs: Any) -> dict[str, Any]:
        """Validate that required inputs are present and apply defaults.

        Args:
            **kwargs: Input field values to validate.

        Returns:
            The validated input dictionary with defaults filled in.

        Raises:
            SignatureError: If a required input field is missing.
        """
        validated: dict[str, Any] = {}

        for field_name, field_spec in cls._input_fields.items():
            if field_name in kwargs:
                validated[field_name] = kwargs[field_name]
            elif not field_spec.required and field_spec.default is not None:
                validated[field_name] = field_spec.default
            elif not field_spec.required:
                validated[field_name] = ""
            else:
                raise SignatureError(
                    message=f"Missing required input field: {field_name}",
                    details={"field": field_name, "signature": cls.__name__},
                )

        return validated

    @classmethod
    def validate_outputs(cls, outputs: dict[str, Any]) -> dict[str, Any]:
        """Validate that required outputs were produced by the LLM.

        Missing required fields are set to empty strings rather than raising,
        since LLM output is inherently unreliable.

        Args:
            outputs: Parsed output dictionary from :meth:`parse_output`.

        Returns:
            The validated output dictionary with defaults filled in.
        """
        validated: dict[str, Any] = {}

        for field_name, field_spec in cls._output_fields.items():
            if field_name in outputs:
                validated[field_name] = outputs[field_name]
            elif not field_spec.required and field_spec.default is not None:
                validated[field_name] = field_spec.default
            elif not field_spec.required:
                validated[field_name] = ""
            else:
                logger.warning(
                    "Missing required output field: %s in signature %s",
                    field_name,
                    cls.__name__,
                )
                # Instead of raising, set empty string — LLM output is
                # inherently unreliable and we prefer graceful degradation.
                validated[field_name] = ""

        return validated


__all__ = [
    "SignatureField",
    "InputField",
    "OutputField",
    "SignatureMeta",
    "Signature",
]
