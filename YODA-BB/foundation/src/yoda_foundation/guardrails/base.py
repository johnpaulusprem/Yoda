"""
Base classes for the Guardrails system.

This module provides abstract base classes for all guardrail implementations,
defining the common interface and behavior patterns.

Example:
    ```python
    from yoda_foundation.guardrails.base import (
        BaseGuardrail,
        InputGuardrail,
        OutputGuardrail,
        DialogGuardrail,
        RetrievalGuardrail,
    )

    class CustomInputGuardrail(InputGuardrail):
        async def _check_impl(
            self,
            content: str,
            context: Dict[str, Any],
            security_context: SecurityContext,
        ) -> GuardrailResult:
            # Custom implementation
            if "forbidden" in content.lower():
                return GuardrailResult(
                    passed=False,
                    action=GuardrailAction.BLOCK,
                    risk_level=RiskLevel.HIGH,
                    violations=[...],
                )
            return GuardrailResult(
                passed=True,
                action=GuardrailAction.ALLOW,
                risk_level=RiskLevel.NONE,
            )
    ```
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from yoda_foundation.guardrails.schemas import (
    DialogContext,
    GuardrailAction,
    GuardrailConfig,
    GuardrailResult,
    GuardrailType,
    RetrievalContext,
    RiskLevel,
    Violation,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


class BaseGuardrail(ABC):
    """
    Abstract base class for all guardrails.

    Provides common functionality for guardrail implementations including
    configuration management, logging, and result handling.

    Attributes:
        guardrail_id: Unique identifier for this guardrail instance
        guardrail_type: Type of guardrail (INPUT, OUTPUT, etc.)
        priority: Execution priority (lower = higher priority)
        enabled: Whether the guardrail is active
        config: Configuration for this guardrail

    Example:
        ```python
        class MyGuardrail(BaseGuardrail):
            def __init__(self):
                super().__init__(
                    guardrail_id="my_guardrail",
                    guardrail_type=GuardrailType.INPUT,
                    priority=10,
                )

            async def _check_impl(
                self,
                content: str,
                context: Dict[str, Any],
                security_context: SecurityContext,
            ) -> GuardrailResult:
                # Implementation
                ...
        ```
    """

    def __init__(
        self,
        guardrail_id: str | None = None,
        guardrail_type: GuardrailType = GuardrailType.INPUT,
        priority: int = 100,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the base guardrail.

        Args:
            guardrail_id: Unique identifier (auto-generated if not provided)
            guardrail_type: Type of guardrail
            priority: Execution priority (lower = higher priority)
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        self.guardrail_id = guardrail_id or f"guardrail_{uuid.uuid4().hex[:8]}"
        self.guardrail_type = guardrail_type
        self.priority = priority
        self.enabled = enabled
        self.config = config or GuardrailConfig()
        self._name = self.__class__.__name__

    @property
    def name(self) -> str:
        """Get the guardrail name."""
        return self._name

    async def check(
        self,
        content: str,
        context: dict[str, Any] | None = None,
        *,
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Check content against this guardrail.

        This method wraps the implementation with logging, timing,
        and error handling.

        Args:
            content: Content to check
            context: Additional context for the check
            security_context: Security context for authorization

        Returns:
            GuardrailResult with check outcome

        Raises:
            GuardrailError: If check fails and fail_closed is True

        Example:
            ```python
            result = await guardrail.check(
                content="User message here",
                context={"source": "api"},
                security_context=security_ctx,
            )

            if not result.passed:
                handle_violation(result)
            ```
        """
        if not self.enabled:
            return GuardrailResult(
                passed=True,
                action=GuardrailAction.ALLOW,
                risk_level=RiskLevel.NONE,
                guardrail_id=self.guardrail_id,
                metadata={"skipped": True, "reason": "guardrail_disabled"},
            )

        context = context or {}
        start_time = time.perf_counter()

        try:
            logger.debug(
                f"Running guardrail check: {self.name}",
                guardrail_id=self.guardrail_id,
                content_length=len(content),
            )

            result = await self._check_impl(content, context, security_context)

            # Add metadata
            execution_time = (time.perf_counter() - start_time) * 1000
            result.guardrail_id = self.guardrail_id
            result.execution_time_ms = execution_time
            result.original_content = content

            # Log violations if configured
            if self.config.log_violations and result.violations:
                logger.warning(
                    f"Guardrail violations detected: {self.name}",
                    guardrail_id=self.guardrail_id,
                    violation_count=len(result.violations),
                    risk_level=result.risk_level.value,
                    action=result.action.value,
                )

            return result

        except (TypeError, ValueError, RuntimeError, KeyError, AttributeError, OSError) as e:
            execution_time = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"Guardrail check failed: {self.name}",
                guardrail_id=self.guardrail_id,
                error=str(e),
            )

            # Fail closed or open based on config
            if self.config.fail_closed:
                return GuardrailResult(
                    passed=False,
                    action=GuardrailAction.BLOCK,
                    risk_level=RiskLevel.HIGH,
                    violations=[
                        Violation(
                            rule_id=f"{self.guardrail_id}_error",
                            rule_name=f"{self.name} Error",
                            severity=RiskLevel.HIGH,
                            description=f"Guardrail check failed: {e!s}",
                        )
                    ],
                    guardrail_id=self.guardrail_id,
                    execution_time_ms=execution_time,
                    metadata={"error": str(e), "fail_closed": True},
                )
            else:
                return GuardrailResult(
                    passed=True,
                    action=GuardrailAction.WARN,
                    risk_level=RiskLevel.LOW,
                    guardrail_id=self.guardrail_id,
                    execution_time_ms=execution_time,
                    metadata={"error": str(e), "fail_open": True},
                )

    @abstractmethod
    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Implementation of the guardrail check.

        Subclasses must override this method to provide
        the actual guardrail logic.

        Args:
            content: Content to check
            context: Additional context
            security_context: Security context

        Returns:
            GuardrailResult with check outcome
        """
        pass

    def _create_violation(
        self,
        rule_id: str,
        rule_name: str,
        severity: RiskLevel,
        description: str,
        evidence: str | None = None,
        location: tuple[int, int] | None = None,
        **metadata: Any,
    ) -> Violation:
        """
        Helper method to create a violation.

        Args:
            rule_id: Unique rule identifier
            rule_name: Human-readable name
            severity: Risk level
            description: Description of violation
            evidence: Content that triggered violation
            location: (start, end) indices
            **metadata: Additional metadata

        Returns:
            Violation instance
        """
        return Violation(
            rule_id=rule_id,
            rule_name=rule_name,
            severity=severity,
            description=description,
            evidence=evidence,
            location=location,
            metadata=metadata,
        )

    def _create_pass_result(
        self,
        risk_level: RiskLevel = RiskLevel.NONE,
        **metadata: Any,
    ) -> GuardrailResult:
        """
        Helper method to create a passing result.

        Args:
            risk_level: Risk level (default NONE)
            **metadata: Additional metadata

        Returns:
            Passing GuardrailResult
        """
        return GuardrailResult(
            passed=True,
            action=GuardrailAction.ALLOW,
            risk_level=risk_level,
            violations=[],
            metadata=metadata,
        )

    def _create_fail_result(
        self,
        violations: list[Violation],
        action: GuardrailAction | None = None,
        risk_level: RiskLevel | None = None,
        modified_content: str | None = None,
        **metadata: Any,
    ) -> GuardrailResult:
        """
        Helper method to create a failing result.

        Args:
            violations: List of violations
            action: Action to take (default from config)
            risk_level: Risk level (default from highest violation)
            modified_content: Modified content if applicable
            **metadata: Additional metadata

        Returns:
            Failing GuardrailResult
        """
        # Determine risk level from violations if not specified
        if risk_level is None and violations:
            severities = [v.severity for v in violations]
            risk_level = max(
                severities,
                key=lambda s: [
                    RiskLevel.NONE,
                    RiskLevel.LOW,
                    RiskLevel.MEDIUM,
                    RiskLevel.HIGH,
                    RiskLevel.CRITICAL,
                ].index(s),
            )
        risk_level = risk_level or RiskLevel.MEDIUM

        # Determine action if not specified
        if action is None:
            action = self.config.default_action

        return GuardrailResult(
            passed=False,
            action=action,
            risk_level=risk_level,
            violations=violations,
            modified_content=modified_content,
            metadata=metadata,
        )

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"{self.__class__.__name__}("
            f"id={self.guardrail_id!r}, "
            f"type={self.guardrail_type.value!r}, "
            f"priority={self.priority}, "
            f"enabled={self.enabled})"
        )


class InputGuardrail(BaseGuardrail):
    """
    Base class for input validation guardrails.

    Input guardrails check user input before it's processed by the agent.

    Example:
        ```python
        class ProfanityFilter(InputGuardrail):
            async def _check_impl(
                self,
                content: str,
                context: Dict[str, Any],
                security_context: SecurityContext,
            ) -> GuardrailResult:
                if contains_profanity(content):
                    return self._create_fail_result(
                        violations=[
                            self._create_violation(
                                rule_id="profanity_001",
                                rule_name="Profanity Filter",
                                severity=RiskLevel.MEDIUM,
                                description="Content contains profanity",
                            )
                        ]
                    )
                return self._create_pass_result()
        ```
    """

    def __init__(
        self,
        guardrail_id: str | None = None,
        priority: int = 100,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the input guardrail.

        Args:
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id,
            guardrail_type=GuardrailType.INPUT,
            priority=priority,
            enabled=enabled,
            config=config,
        )


class OutputGuardrail(BaseGuardrail):
    """
    Base class for output filtering guardrails.

    Output guardrails check agent output before it's returned to the user.

    Example:
        ```python
        class PIIRedactor(OutputGuardrail):
            async def _check_impl(
                self,
                content: str,
                context: Dict[str, Any],
                security_context: SecurityContext,
            ) -> GuardrailResult:
                pii_matches = detect_pii(content)
                if pii_matches:
                    redacted = redact_pii(content, pii_matches)
                    return self._create_fail_result(
                        violations=[...],
                        action=GuardrailAction.MODIFY,
                        modified_content=redacted,
                    )
                return self._create_pass_result()
        ```
    """

    def __init__(
        self,
        guardrail_id: str | None = None,
        priority: int = 100,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the output guardrail.

        Args:
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id,
            guardrail_type=GuardrailType.OUTPUT,
            priority=priority,
            enabled=enabled,
            config=config,
        )


class DialogGuardrail(BaseGuardrail):
    """
    Base class for dialog-level guardrails.

    Dialog guardrails check conversation flow and context across turns.

    Example:
        ```python
        class TopicDriftDetector(DialogGuardrail):
            async def check_dialog(
                self,
                dialog_context: DialogContext,
                security_context: SecurityContext,
            ) -> GuardrailResult:
                if detect_topic_drift(dialog_context):
                    return self._create_fail_result(
                        violations=[...],
                        action=GuardrailAction.WARN,
                    )
                return self._create_pass_result()
        ```
    """

    def __init__(
        self,
        guardrail_id: str | None = None,
        priority: int = 100,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the dialog guardrail.

        Args:
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id,
            guardrail_type=GuardrailType.DIALOG,
            priority=priority,
            enabled=enabled,
            config=config,
        )

    async def check_dialog(
        self,
        dialog_context: DialogContext,
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Check dialog context against this guardrail.

        Args:
            dialog_context: Dialog context with conversation history
            security_context: Security context

        Returns:
            GuardrailResult with check outcome

        Example:
            ```python
            result = await guardrail.check_dialog(
                dialog_context=dialog_ctx,
                security_context=security_ctx,
            )
            ```
        """
        # Convert dialog to content for base check
        messages = dialog_context.messages
        if messages:
            last_message = messages[-1]
            content = last_message.get("content", "")
        else:
            content = ""

        context = {
            "dialog_context": dialog_context,
            "messages": messages,
            "turn_count": dialog_context.turn_count,
        }

        return await self.check(content, context, security_context)

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Default implementation calls dialog-specific check.

        Subclasses should override _check_dialog_impl instead.
        """
        dialog_context = context.get("dialog_context")
        if dialog_context:
            return await self._check_dialog_impl(dialog_context, context, security_context)
        return self._create_pass_result()

    async def _check_dialog_impl(
        self,
        dialog_context: DialogContext,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Implementation of dialog-specific check.

        Subclasses should override this method.

        Args:
            dialog_context: Dialog context
            context: Additional context
            security_context: Security context

        Returns:
            GuardrailResult with check outcome
        """
        return self._create_pass_result()


class RetrievalGuardrail(BaseGuardrail):
    """
    Base class for retrieval guardrails.

    Retrieval guardrails check documents retrieved in RAG pipelines.

    Example:
        ```python
        class SourceValidator(RetrievalGuardrail):
            async def check_retrieval(
                self,
                retrieval_context: RetrievalContext,
                security_context: SecurityContext,
            ) -> GuardrailResult:
                for doc in retrieval_context.documents:
                    if not is_trusted_source(doc["source"]):
                        return self._create_fail_result(
                            violations=[...],
                        )
                return self._create_pass_result()
        ```
    """

    def __init__(
        self,
        guardrail_id: str | None = None,
        priority: int = 100,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the retrieval guardrail.

        Args:
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id,
            guardrail_type=GuardrailType.RETRIEVAL,
            priority=priority,
            enabled=enabled,
            config=config,
        )

    async def check_retrieval(
        self,
        retrieval_context: RetrievalContext,
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Check retrieval context against this guardrail.

        Args:
            retrieval_context: Retrieval context with documents
            security_context: Security context

        Returns:
            GuardrailResult with check outcome

        Example:
            ```python
            result = await guardrail.check_retrieval(
                retrieval_context=retrieval_ctx,
                security_context=security_ctx,
            )
            ```
        """
        # Combine document contents for base check
        contents = []
        for doc in retrieval_context.documents:
            if isinstance(doc, dict):
                contents.append(doc.get("content", str(doc)))
            else:
                contents.append(str(doc))

        content = "\n\n".join(contents)
        context = {
            "retrieval_context": retrieval_context,
            "query": retrieval_context.query,
            "document_count": len(retrieval_context.documents),
        }

        return await self.check(content, context, security_context)

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Default implementation calls retrieval-specific check.

        Subclasses should override _check_retrieval_impl instead.
        """
        retrieval_context = context.get("retrieval_context")
        if retrieval_context:
            return await self._check_retrieval_impl(retrieval_context, context, security_context)
        return self._create_pass_result()

    async def _check_retrieval_impl(
        self,
        retrieval_context: RetrievalContext,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Implementation of retrieval-specific check.

        Subclasses should override this method.

        Args:
            retrieval_context: Retrieval context
            context: Additional context
            security_context: Security context

        Returns:
            GuardrailResult with check outcome
        """
        return self._create_pass_result()


class ExecutionGuardrail(BaseGuardrail):
    """
    Base class for execution guardrails.

    Execution guardrails check agent actions before they're executed.

    Example:
        ```python
        class ActionLimiter(ExecutionGuardrail):
            async def check_execution(
                self,
                action: str,
                parameters: Dict[str, Any],
                security_context: SecurityContext,
            ) -> GuardrailResult:
                if action in DANGEROUS_ACTIONS:
                    return self._create_fail_result(
                        violations=[...],
                        action=GuardrailAction.ESCALATE,
                    )
                return self._create_pass_result()
        ```
    """

    def __init__(
        self,
        guardrail_id: str | None = None,
        priority: int = 100,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the execution guardrail.

        Args:
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id,
            guardrail_type=GuardrailType.EXECUTION,
            priority=priority,
            enabled=enabled,
            config=config,
        )

    async def check_execution(
        self,
        action: str,
        parameters: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Check action execution against this guardrail.

        Args:
            action: Action identifier
            parameters: Action parameters
            security_context: Security context

        Returns:
            GuardrailResult with check outcome

        Example:
            ```python
            result = await guardrail.check_execution(
                action="file_write",
                parameters={"path": "/tmp/file.txt"},
                security_context=security_ctx,
            )
            ```
        """
        content = f"Action: {action}\nParameters: {parameters}"
        context = {
            "action": action,
            "parameters": parameters,
            "execution_check": True,
        }

        return await self.check(content, context, security_context)

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Default implementation calls execution-specific check.

        Subclasses should override _check_execution_impl instead.
        """
        if context.get("execution_check"):
            action = context.get("action", "")
            parameters = context.get("parameters", {})
            return await self._check_execution_impl(action, parameters, context, security_context)
        return self._create_pass_result()

    async def _check_execution_impl(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Implementation of execution-specific check.

        Subclasses should override this method.

        Args:
            action: Action identifier
            parameters: Action parameters
            context: Additional context
            security_context: Security context

        Returns:
            GuardrailResult with check outcome
        """
        return self._create_pass_result()
