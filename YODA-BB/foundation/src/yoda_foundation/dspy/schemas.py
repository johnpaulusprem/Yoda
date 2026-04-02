"""DSPy schema definitions for field types, signatures, and module specs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FieldType(Enum):
    """Supported primitive field types for DSPy signature declarations."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    LIST = "list"
    DICT = "dict"


class ModuleType(Enum):
    """Types of DSPy modules (Predict vs Chain-of-Thought)."""

    PREDICT = "predict"
    CHAIN_OF_THOUGHT = "chain_of_thought"


@dataclass
class FieldSpec:
    """Specification for a single input or output field in a signature.

    Attributes:
        name: Field name as it appears in the prompt.
        field_type: The primitive type of the field value.
        description: Human-readable description shown to the LLM.
        required: Whether the field must be provided (inputs) or produced (outputs).
        default: Default value when the field is not required.
    """

    name: str
    field_type: FieldType
    description: str
    required: bool = True
    default: Any = None


@dataclass
class SignatureSpec:
    """Specification for a complete signature (inputs and outputs).

    Attributes:
        name: Unique name identifying this signature.
        description: Purpose of the signature, used as the LLM system instruction.
        input_fields: Ordered list of input field specifications.
        output_fields: Ordered list of output field specifications.
    """

    name: str
    description: str
    input_fields: list[FieldSpec] = field(default_factory=list)
    output_fields: list[FieldSpec] = field(default_factory=list)


@dataclass
class ModuleSpec:
    """Specification for a DSPy module instance.

    Attributes:
        name: Unique name identifying this module.
        module_type: Whether this is a Predict or Chain-of-Thought module.
        signature_spec: The signature defining inputs and outputs.
        config: Additional configuration overrides (temperature, model, etc.).
    """

    name: str
    module_type: ModuleType
    signature_spec: SignatureSpec
    config: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "FieldType",
    "ModuleType",
    "FieldSpec",
    "SignatureSpec",
    "ModuleSpec",
]
