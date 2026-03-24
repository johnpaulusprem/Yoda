"""
Rail specification DSL for declarative guardrail definitions.

This module provides a domain-specific language (DSL) for defining
guardrails declaratively using YAML or JSON configuration.

Example:
    ```python
    from yoda_foundation.guardrails.rail import (
        Rail,
        RailParser,
        RailValidator,
    )

    # Define rail in YAML
    rail_yaml = '''
    name: customer_support_rail
    description: Guardrails for customer support chatbot
    version: "1.0"

    input_guardrails:
      - type: jailbreak
        sensitivity: 0.7
      - type: toxicity
        threshold: 0.6
      - type: pii
        redact: true

    output_guardrails:
      - type: grounding
        threshold: 0.8
      - type: topic
        allowed_topics:
          - customer_support
          - billing
    '''

    # Parse and create rail
    parser = RailParser()
    rail = parser.parse_yaml(rail_yaml)

    # Validate rail
    validator = RailValidator()
    validation_result = validator.validate(rail)

    # Use rail to create guardrails
    guardrails = rail.create_guardrails()
    ```
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from yoda_foundation.guardrails.base import (
    BaseGuardrail,
)
from yoda_foundation.guardrails.schemas import (
    GuardrailConfig,
)
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


@dataclass
class RailGuardrailSpec:
    """
    Specification for a guardrail within a rail.

    Attributes:
        guardrail_type: Type of guardrail
        enabled: Whether guardrail is enabled
        priority: Execution priority
        config: Guardrail-specific configuration

    Example:
        ```python
        spec = RailGuardrailSpec(
            guardrail_type="jailbreak",
            enabled=True,
            priority=1,
            config={"sensitivity": 0.7},
        )
        ```
    """

    guardrail_type: str
    enabled: bool = True
    priority: int = 100
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class Rail:
    """
    Declarative guardrail specification.

    A Rail defines a complete guardrail configuration including
    input, output, dialog, and retrieval guardrails.

    Attributes:
        name: Rail name
        description: Rail description
        version: Version string
        input_guardrails: Input guardrail specifications
        output_guardrails: Output guardrail specifications
        dialog_guardrails: Dialog guardrail specifications
        retrieval_guardrails: Retrieval guardrail specifications
        global_config: Global configuration applied to all guardrails
        metadata: Additional metadata

    Example:
        ```python
        rail = Rail(
            name="support_bot",
            description="Guardrails for support chatbot",
            version="1.0",
            input_guardrails=[
                RailGuardrailSpec(
                    guardrail_type="jailbreak",
                    config={"sensitivity": 0.7},
                ),
            ],
            output_guardrails=[
                RailGuardrailSpec(
                    guardrail_type="pii",
                    config={"redact": True},
                ),
            ],
        )
        ```
    """

    name: str
    description: str = ""
    version: str = "1.0"
    input_guardrails: list[RailGuardrailSpec] = field(default_factory=list)
    output_guardrails: list[RailGuardrailSpec] = field(default_factory=list)
    dialog_guardrails: list[RailGuardrailSpec] = field(default_factory=list)
    retrieval_guardrails: list[RailGuardrailSpec] = field(default_factory=list)
    global_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def create_guardrails(self) -> list[BaseGuardrail]:
        """
        Create guardrail instances from specifications.

        Returns:
            List of configured guardrail instances

        Example:
            ```python
            guardrails = rail.create_guardrails()
            for g in guardrails:
                engine.register_guardrail(g)
            ```
        """
        from yoda_foundation.guardrails.content_safety import (
            HateSpeechGuardrail,
            PIIGuardrail,
            ProfanityGuardrail,
            ToxicityGuardrail,
            ViolenceGuardrail,
        )
        from yoda_foundation.guardrails.fact_check import (
            FactCheckGuardrail,
            GroundingGuardrail,
        )
        from yoda_foundation.guardrails.jailbreak import (
            EncodingGuardrail,
            JailbreakDetector,
            PromptInjectionGuardrail,
            RolePlayGuardrail,
        )
        from yoda_foundation.guardrails.moderation import ModerationGuardrail
        from yoda_foundation.guardrails.topic import TopicGuardrail

        # Mapping of type names to guardrail classes
        guardrail_classes: dict[str, type[BaseGuardrail]] = {
            "jailbreak": JailbreakDetector,
            "prompt_injection": PromptInjectionGuardrail,
            "roleplay": RolePlayGuardrail,
            "encoding": EncodingGuardrail,
            "toxicity": ToxicityGuardrail,
            "profanity": ProfanityGuardrail,
            "pii": PIIGuardrail,
            "hate_speech": HateSpeechGuardrail,
            "violence": ViolenceGuardrail,
            "topic": TopicGuardrail,
            "fact_check": FactCheckGuardrail,
            "grounding": GroundingGuardrail,
            "moderation": ModerationGuardrail,
        }

        guardrails: list[BaseGuardrail] = []

        # Create global config
        global_config = GuardrailConfig(**self.global_config)

        # Create input guardrails
        for spec in self.input_guardrails:
            guardrail = self._create_guardrail(spec, guardrail_classes, global_config)
            if guardrail:
                guardrails.append(guardrail)

        # Create output guardrails
        for spec in self.output_guardrails:
            guardrail = self._create_guardrail(spec, guardrail_classes, global_config)
            if guardrail:
                guardrails.append(guardrail)

        # Create dialog guardrails
        for spec in self.dialog_guardrails:
            guardrail = self._create_guardrail(spec, guardrail_classes, global_config)
            if guardrail:
                guardrails.append(guardrail)

        # Create retrieval guardrails
        for spec in self.retrieval_guardrails:
            guardrail = self._create_guardrail(spec, guardrail_classes, global_config)
            if guardrail:
                guardrails.append(guardrail)

        return guardrails

    def _create_guardrail(
        self,
        spec: RailGuardrailSpec,
        guardrail_classes: dict[str, type[BaseGuardrail]],
        global_config: GuardrailConfig,
    ) -> BaseGuardrail | None:
        """
        Create a guardrail from specification.

        Args:
            spec: Guardrail specification
            guardrail_classes: Available guardrail classes
            global_config: Global configuration

        Returns:
            Guardrail instance or None
        """
        guardrail_class = guardrail_classes.get(spec.guardrail_type)

        if not guardrail_class:
            logger.warning(f"Unknown guardrail type: {spec.guardrail_type}")
            return None

        try:
            # Prepare kwargs
            kwargs = {
                "enabled": spec.enabled,
                "priority": spec.priority,
                "config": global_config,
                **spec.config,
            }

            return guardrail_class(**kwargs)
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.error(f"Failed to create guardrail {spec.guardrail_type}: {e}")
            return None

    def to_dict(self) -> dict[str, Any]:
        """Convert rail to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "input_guardrails": [
                {
                    "type": g.guardrail_type,
                    "enabled": g.enabled,
                    "priority": g.priority,
                    "config": g.config,
                }
                for g in self.input_guardrails
            ],
            "output_guardrails": [
                {
                    "type": g.guardrail_type,
                    "enabled": g.enabled,
                    "priority": g.priority,
                    "config": g.config,
                }
                for g in self.output_guardrails
            ],
            "dialog_guardrails": [
                {
                    "type": g.guardrail_type,
                    "enabled": g.enabled,
                    "priority": g.priority,
                    "config": g.config,
                }
                for g in self.dialog_guardrails
            ],
            "retrieval_guardrails": [
                {
                    "type": g.guardrail_type,
                    "enabled": g.enabled,
                    "priority": g.priority,
                    "config": g.config,
                }
                for g in self.retrieval_guardrails
            ],
            "global_config": self.global_config,
            "metadata": self.metadata,
        }


class RailParser:
    """
    Parser for rail specifications.

    Parses YAML or JSON rail definitions into Rail objects.

    Example:
        ```python
        parser = RailParser()

        # Parse from YAML
        rail = parser.parse_yaml(yaml_string)

        # Parse from JSON
        rail = parser.parse_json(json_string)

        # Parse from file
        rail = parser.parse_file("guardrails.yaml")
        ```
    """

    def parse_yaml(self, yaml_content: str) -> Rail:
        """
        Parse rail from YAML string.

        Args:
            yaml_content: YAML content

        Returns:
            Rail object

        Raises:
            ValueError: If YAML is invalid
        """
        try:
            import yaml

            data = yaml.safe_load(yaml_content)
            return self._parse_dict(data)
        except ImportError:
            # Fall back to simple parsing if yaml not available
            raise ValueError("PyYAML is required for YAML parsing")
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            raise ValueError(f"Failed to parse YAML: {e}")

    def parse_json(self, json_content: str) -> Rail:
        """
        Parse rail from JSON string.

        Args:
            json_content: JSON content

        Returns:
            Rail object

        Raises:
            ValueError: If JSON is invalid
        """
        try:
            data = json.loads(json_content)
            return self._parse_dict(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON: {e}")

    def parse_file(self, file_path: str) -> Rail:
        """
        Parse rail from file.

        Args:
            file_path: Path to rail file

        Returns:
            Rail object

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is invalid
        """
        with open(file_path) as f:
            content = f.read()

        if file_path.endswith(".yaml") or file_path.endswith(".yml"):
            return self.parse_yaml(content)
        elif file_path.endswith(".json"):
            return self.parse_json(content)
        else:
            # Try JSON first, then YAML
            try:
                return self.parse_json(content)
            except ValueError:
                return self.parse_yaml(content)

    def _parse_dict(self, data: dict[str, Any]) -> Rail:
        """
        Parse rail from dictionary.

        Args:
            data: Dictionary data

        Returns:
            Rail object
        """
        input_guardrails = []
        for g in data.get("input_guardrails", []):
            input_guardrails.append(self._parse_guardrail_spec(g))

        output_guardrails = []
        for g in data.get("output_guardrails", []):
            output_guardrails.append(self._parse_guardrail_spec(g))

        dialog_guardrails = []
        for g in data.get("dialog_guardrails", []):
            dialog_guardrails.append(self._parse_guardrail_spec(g))

        retrieval_guardrails = []
        for g in data.get("retrieval_guardrails", []):
            retrieval_guardrails.append(self._parse_guardrail_spec(g))

        return Rail(
            name=data.get("name", "unnamed_rail"),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            input_guardrails=input_guardrails,
            output_guardrails=output_guardrails,
            dialog_guardrails=dialog_guardrails,
            retrieval_guardrails=retrieval_guardrails,
            global_config=data.get("global_config", {}),
            metadata=data.get("metadata", {}),
        )

    def _parse_guardrail_spec(self, data: dict[str, Any]) -> RailGuardrailSpec:
        """Parse guardrail specification from dictionary."""
        config = {k: v for k, v in data.items() if k not in ("type", "enabled", "priority")}

        return RailGuardrailSpec(
            guardrail_type=data.get("type", "unknown"),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 100),
            config=config,
        )


@dataclass
class ValidationError:
    """
    Validation error for rail specifications.

    Attributes:
        path: Path to the error in the rail spec
        message: Error message
        severity: Error severity
    """

    path: str
    message: str
    severity: str = "error"


@dataclass
class ValidationResult:
    """
    Result of rail validation.

    Attributes:
        valid: Whether rail is valid
        errors: List of validation errors
        warnings: List of validation warnings
    """

    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)


class RailValidator:
    """
    Validator for rail specifications.

    Validates rail definitions for correctness and best practices.

    Example:
        ```python
        validator = RailValidator()

        result = validator.validate(rail)

        if not result.valid:
            for error in result.errors:
                print(f"Error at {error.path}: {error.message}")
        ```
    """

    VALID_GUARDRAIL_TYPES = {
        "jailbreak",
        "prompt_injection",
        "roleplay",
        "encoding",
        "toxicity",
        "profanity",
        "pii",
        "hate_speech",
        "violence",
        "topic",
        "fact_check",
        "grounding",
        "moderation",
    }

    def validate(self, rail: Rail) -> ValidationResult:
        """
        Validate a rail specification.

        Args:
            rail: Rail to validate

        Returns:
            ValidationResult with errors and warnings
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationError] = []

        # Validate name
        if not rail.name:
            errors.append(
                ValidationError(
                    path="name",
                    message="Rail name is required",
                )
            )

        # Validate version
        if not rail.version:
            warnings.append(
                ValidationError(
                    path="version",
                    message="Version is recommended",
                    severity="warning",
                )
            )

        # Validate guardrails
        self._validate_guardrails(rail.input_guardrails, "input_guardrails", errors, warnings)
        self._validate_guardrails(rail.output_guardrails, "output_guardrails", errors, warnings)
        self._validate_guardrails(rail.dialog_guardrails, "dialog_guardrails", errors, warnings)
        self._validate_guardrails(
            rail.retrieval_guardrails, "retrieval_guardrails", errors, warnings
        )

        # Check for at least one guardrail
        total_guardrails = (
            len(rail.input_guardrails)
            + len(rail.output_guardrails)
            + len(rail.dialog_guardrails)
            + len(rail.retrieval_guardrails)
        )
        if total_guardrails == 0:
            warnings.append(
                ValidationError(
                    path="guardrails",
                    message="Rail has no guardrails defined",
                    severity="warning",
                )
            )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _validate_guardrails(
        self,
        guardrails: list[RailGuardrailSpec],
        path: str,
        errors: list[ValidationError],
        warnings: list[ValidationError],
    ) -> None:
        """Validate a list of guardrail specifications."""
        for i, spec in enumerate(guardrails):
            spec_path = f"{path}[{i}]"

            # Validate type
            if spec.guardrail_type not in self.VALID_GUARDRAIL_TYPES:
                errors.append(
                    ValidationError(
                        path=f"{spec_path}.type",
                        message=f"Unknown guardrail type: {spec.guardrail_type}",
                    )
                )

            # Validate priority
            if spec.priority < 0:
                errors.append(
                    ValidationError(
                        path=f"{spec_path}.priority",
                        message="Priority must be non-negative",
                    )
                )

            # Type-specific validation
            self._validate_guardrail_config(spec, spec_path, errors, warnings)

    def _validate_guardrail_config(
        self,
        spec: RailGuardrailSpec,
        path: str,
        errors: list[ValidationError],
        warnings: list[ValidationError],
    ) -> None:
        """Validate guardrail-specific configuration."""
        config = spec.config

        # Validate threshold values
        for key in ["threshold", "sensitivity", "confidence_threshold"]:
            if key in config:
                value = config[key]
                if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                    errors.append(
                        ValidationError(
                            path=f"{path}.config.{key}",
                            message=f"{key} must be between 0 and 1",
                        )
                    )

        # Validate topic guardrail
        if spec.guardrail_type == "topic":
            if "allowed_topics" in config:
                topics = config["allowed_topics"]
                if not isinstance(topics, list) or len(topics) == 0:
                    warnings.append(
                        ValidationError(
                            path=f"{path}.config.allowed_topics",
                            message="allowed_topics should be a non-empty list",
                            severity="warning",
                        )
                    )

        # Validate PII guardrail
        if spec.guardrail_type == "pii":
            if "pii_types" in config:
                valid_types = {"email", "phone", "ssn", "credit_card", "ip_address"}
                pii_types = config["pii_types"]
                if isinstance(pii_types, list):
                    for t in pii_types:
                        if t not in valid_types:
                            warnings.append(
                                ValidationError(
                                    path=f"{path}.config.pii_types",
                                    message=f"Unknown PII type: {t}",
                                    severity="warning",
                                )
                            )
