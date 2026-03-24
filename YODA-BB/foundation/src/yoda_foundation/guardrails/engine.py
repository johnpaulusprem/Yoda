"""
Main guardrail engine for the Agentic AI Component Library.

This module provides the central GuardrailEngine class that orchestrates
all guardrail checks for input, output, dialog, and retrieval content.

Example:
    ```python
    from yoda_foundation.guardrails import (
        GuardrailEngine,
        GuardrailConfig,
        ToxicityGuardrail,
        PIIGuardrail,
        JailbreakDetector,
    )

    # Configure and create engine
    config = GuardrailConfig(
        fail_on_block=True,
        risk_threshold=RiskLevel.MEDIUM,
    )
    engine = GuardrailEngine(config)

    # Register guardrails
    engine.register_guardrail(ToxicityGuardrail(threshold=0.7))
    engine.register_guardrail(PIIGuardrail(redact=True))
    engine.register_guardrail(JailbreakDetector())

    # Check input
    result = await engine.check_input(
        content=user_message,
        security_context=ctx,
    )

    if not result.passed:
        handle_violation(result)
    ```
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from yoda_foundation.guardrails.base import (
    BaseGuardrail,
)
from yoda_foundation.guardrails.schemas import (
    DialogContext,
    GuardrailAction,
    GuardrailConfig,
    GuardrailResult,
    GuardrailType,
    RetrievalContext,
    RiskLevel,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


class GuardrailEngine:
    """
    Central engine for orchestrating guardrail checks.

    The GuardrailEngine manages a collection of guardrails and
    provides methods for checking content against them.

    Attributes:
        config: Engine configuration
        input_guardrails: List of input guardrails
        output_guardrails: List of output guardrails
        dialog_guardrails: List of dialog guardrails
        retrieval_guardrails: List of retrieval guardrails
        execution_guardrails: List of execution guardrails

    Example:
        ```python
        engine = GuardrailEngine(config)

        # Register guardrails
        engine.register_guardrail(ToxicityGuardrail())
        engine.register_guardrail(JailbreakDetector())

        # Check content
        result = await engine.check_input(content, security_context)

        if result.action == GuardrailAction.BLOCK:
            return error_response("Content blocked")
        elif result.action == GuardrailAction.MODIFY:
            content = result.modified_content
        ```
    """

    def __init__(self, config: GuardrailConfig | None = None) -> None:
        """
        Initialize the guardrail engine.

        Args:
            config: Engine configuration
        """
        self.config = config or GuardrailConfig()
        self._guardrails: dict[str, BaseGuardrail] = {}
        self._guardrails_by_type: dict[GuardrailType, list[BaseGuardrail]] = {
            GuardrailType.INPUT: [],
            GuardrailType.OUTPUT: [],
            GuardrailType.DIALOG: [],
            GuardrailType.RETRIEVAL: [],
            GuardrailType.EXECUTION: [],
        }

    @property
    def input_guardrails(self) -> list[BaseGuardrail]:
        """Get input guardrails."""
        return self._guardrails_by_type[GuardrailType.INPUT]

    @property
    def output_guardrails(self) -> list[BaseGuardrail]:
        """Get output guardrails."""
        return self._guardrails_by_type[GuardrailType.OUTPUT]

    @property
    def dialog_guardrails(self) -> list[BaseGuardrail]:
        """Get dialog guardrails."""
        return self._guardrails_by_type[GuardrailType.DIALOG]

    @property
    def retrieval_guardrails(self) -> list[BaseGuardrail]:
        """Get retrieval guardrails."""
        return self._guardrails_by_type[GuardrailType.RETRIEVAL]

    @property
    def execution_guardrails(self) -> list[BaseGuardrail]:
        """Get execution guardrails."""
        return self._guardrails_by_type[GuardrailType.EXECUTION]

    def register_guardrail(self, guardrail: BaseGuardrail) -> None:
        """
        Register a guardrail with the engine.

        Args:
            guardrail: Guardrail to register

        Example:
            ```python
            engine.register_guardrail(ToxicityGuardrail(threshold=0.7))
            engine.register_guardrail(PIIGuardrail(redact=True))
            ```
        """
        self._guardrails[guardrail.guardrail_id] = guardrail
        self._guardrails_by_type[guardrail.guardrail_type].append(guardrail)

        # Sort by priority
        self._guardrails_by_type[guardrail.guardrail_type].sort(key=lambda g: g.priority)

        logger.info(
            f"Registered guardrail: {guardrail.name}",
            guardrail_id=guardrail.guardrail_id,
            guardrail_type=guardrail.guardrail_type.value,
            priority=guardrail.priority,
        )

    def unregister_guardrail(self, guardrail_id: str) -> bool:
        """
        Remove a guardrail from the engine.

        Args:
            guardrail_id: ID of guardrail to remove

        Returns:
            True if guardrail was removed

        Example:
            ```python
            if engine.unregister_guardrail("toxicity_guardrail"):
                print("Toxicity guardrail removed")
            ```
        """
        guardrail = self._guardrails.pop(guardrail_id, None)

        if guardrail:
            self._guardrails_by_type[guardrail.guardrail_type] = [
                g
                for g in self._guardrails_by_type[guardrail.guardrail_type]
                if g.guardrail_id != guardrail_id
            ]
            logger.info(f"Unregistered guardrail: {guardrail_id}")
            return True

        return False

    def get_guardrail(self, guardrail_id: str) -> BaseGuardrail | None:
        """
        Get a guardrail by ID.

        Args:
            guardrail_id: Guardrail ID

        Returns:
            Guardrail instance or None
        """
        return self._guardrails.get(guardrail_id)

    async def check_input(
        self,
        content: str,
        security_context: SecurityContext,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        """
        Check user input against all input guardrails.

        Args:
            content: User input content
            security_context: Security context
            context: Additional context

        Returns:
            GuardrailResult with check outcome

        Raises:
            ContentBlockedError: If fail_on_block is True and content is blocked

        Example:
            ```python
            result = await engine.check_input(
                content=user_message,
                security_context=ctx,
            )

            if not result.passed:
                if result.action == GuardrailAction.MODIFY:
                    user_message = result.modified_content
                else:
                    return error_response(result.violations)
            ```
        """
        if not self.config.is_type_enabled(GuardrailType.INPUT):
            return self._create_skip_result("input_disabled")

        return await self._run_guardrails(
            guardrails=self.input_guardrails,
            content=content,
            context=context or {},
            security_context=security_context,
            guardrail_type=GuardrailType.INPUT,
        )

    async def check_output(
        self,
        content: str,
        security_context: SecurityContext,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        """
        Check model output against all output guardrails.

        Args:
            content: Model output content
            security_context: Security context
            context: Additional context

        Returns:
            GuardrailResult with check outcome

        Example:
            ```python
            result = await engine.check_output(
                content=llm_response,
                security_context=ctx,
            )

            if result.action == GuardrailAction.MODIFY:
                llm_response = result.modified_content
            ```
        """
        if not self.config.is_type_enabled(GuardrailType.OUTPUT):
            return self._create_skip_result("output_disabled")

        return await self._run_guardrails(
            guardrails=self.output_guardrails,
            content=content,
            context=context or {},
            security_context=security_context,
            guardrail_type=GuardrailType.OUTPUT,
        )

    async def check_dialog(
        self,
        messages: list[dict[str, Any]],
        security_context: SecurityContext,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        """
        Check conversation flow against dialog guardrails.

        Args:
            messages: List of conversation messages
            security_context: Security context
            context: Additional context

        Returns:
            GuardrailResult with check outcome

        Example:
            ```python
            result = await engine.check_dialog(
                messages=[
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi!"},
                ],
                security_context=ctx,
            )
            ```
        """
        if not self.config.is_type_enabled(GuardrailType.DIALOG):
            return self._create_skip_result("dialog_disabled")

        dialog_context = DialogContext(
            messages=messages,
            turn_count=len([m for m in messages if m.get("role") == "user"]),
        )

        # Get content from last message
        content = ""
        if messages:
            content = messages[-1].get("content", "")

        ctx = {
            "dialog_context": dialog_context,
            **(context or {}),
        }

        return await self._run_guardrails(
            guardrails=self.dialog_guardrails,
            content=content,
            context=ctx,
            security_context=security_context,
            guardrail_type=GuardrailType.DIALOG,
        )

    async def check_retrieval(
        self,
        documents: list[dict[str, Any]],
        query: str,
        security_context: SecurityContext,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        """
        Check retrieved documents against retrieval guardrails.

        Args:
            documents: Retrieved documents
            query: Retrieval query
            security_context: Security context
            context: Additional context

        Returns:
            GuardrailResult with check outcome

        Example:
            ```python
            result = await engine.check_retrieval(
                documents=retrieved_docs,
                query=user_query,
                security_context=ctx,
            )

            if not result.passed:
                # Filter out problematic documents
                safe_docs = filter_docs(retrieved_docs, result)
            ```
        """
        if not self.config.is_type_enabled(GuardrailType.RETRIEVAL):
            return self._create_skip_result("retrieval_disabled")

        retrieval_context = RetrievalContext(
            query=query,
            documents=documents,
        )

        # Combine document contents
        contents = []
        for doc in documents:
            if isinstance(doc, dict):
                contents.append(doc.get("content", str(doc)))
            else:
                contents.append(str(doc))

        content = "\n\n".join(contents)

        ctx = {
            "retrieval_context": retrieval_context,
            **(context or {}),
        }

        return await self._run_guardrails(
            guardrails=self.retrieval_guardrails,
            content=content,
            context=ctx,
            security_context=security_context,
            guardrail_type=GuardrailType.RETRIEVAL,
        )

    async def check_execution(
        self,
        action: str,
        parameters: dict[str, Any],
        security_context: SecurityContext,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        """
        Check agent action against execution guardrails.

        Args:
            action: Action identifier
            parameters: Action parameters
            security_context: Security context
            context: Additional context

        Returns:
            GuardrailResult with check outcome

        Example:
            ```python
            result = await engine.check_execution(
                action="file_write",
                parameters={"path": "/tmp/file.txt"},
                security_context=ctx,
            )

            if result.action == GuardrailAction.ESCALATE:
                await request_human_approval(action, parameters)
            ```
        """
        if not self.config.is_type_enabled(GuardrailType.EXECUTION):
            return self._create_skip_result("execution_disabled")

        content = f"Action: {action}\nParameters: {parameters}"

        ctx = {
            "action": action,
            "parameters": parameters,
            "execution_check": True,
            **(context or {}),
        }

        return await self._run_guardrails(
            guardrails=self.execution_guardrails,
            content=content,
            context=ctx,
            security_context=security_context,
            guardrail_type=GuardrailType.EXECUTION,
        )

    async def apply_all(
        self,
        content: str,
        guardrail_type: GuardrailType,
        security_context: SecurityContext,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        """
        Apply all guardrails of a specific type.

        Args:
            content: Content to check
            guardrail_type: Type of guardrails to apply
            security_context: Security context
            context: Additional context

        Returns:
            GuardrailResult with combined check outcome

        Example:
            ```python
            result = await engine.apply_all(
                content=message,
                guardrail_type=GuardrailType.INPUT,
                security_context=ctx,
            )
            ```
        """
        guardrails = self._guardrails_by_type.get(guardrail_type, [])

        return await self._run_guardrails(
            guardrails=guardrails,
            content=content,
            context=context or {},
            security_context=security_context,
            guardrail_type=guardrail_type,
        )

    async def _run_guardrails(
        self,
        guardrails: list[BaseGuardrail],
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
        guardrail_type: GuardrailType,
    ) -> GuardrailResult:
        """
        Run a list of guardrails against content.

        Args:
            guardrails: List of guardrails to run
            content: Content to check
            context: Additional context
            security_context: Security context
            guardrail_type: Type of guardrails

        Returns:
            Merged GuardrailResult
        """
        if not guardrails:
            return self._create_skip_result("no_guardrails")

        start_time = time.perf_counter()

        # Filter enabled guardrails
        active_guardrails = [g for g in guardrails if g.enabled]

        if not active_guardrails:
            return self._create_skip_result("no_active_guardrails")

        results: list[GuardrailResult] = []

        if self.config.parallel_execution:
            # Run guardrails in parallel
            try:
                tasks = [
                    asyncio.wait_for(
                        g.check(content, context, security_context),
                        timeout=self.config.timeout_seconds,
                    )
                    for g in active_guardrails
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Handle exceptions
                processed_results = []
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(
                            f"Guardrail failed: {active_guardrails[i].name}",
                            error=str(result),
                        )
                        if self.config.fail_closed:
                            processed_results.append(
                                self._create_error_result(active_guardrails[i], result)
                            )
                    else:
                        processed_results.append(result)

                results = processed_results

            except TimeoutError:
                logger.error("Guardrail execution timeout")
                if self.config.fail_closed:
                    return self._create_timeout_result()
                return self._create_skip_result("timeout")
        else:
            # Run guardrails sequentially
            for guardrail in active_guardrails:
                try:
                    result = await asyncio.wait_for(
                        guardrail.check(content, context, security_context),
                        timeout=self.config.timeout_seconds,
                    )
                    results.append(result)

                    # Short-circuit on block
                    if result.action == GuardrailAction.BLOCK:
                        break

                except TimeoutError:
                    logger.error(f"Guardrail timeout: {guardrail.name}")
                    if self.config.fail_closed:
                        results.append(self._create_error_result(guardrail, None))
                except (
                    TypeError,
                    ValueError,
                    RuntimeError,
                    KeyError,
                    AttributeError,
                    OSError,
                ) as e:
                    logger.error(f"Guardrail failed: {guardrail.name}", error=str(e))
                    if self.config.fail_closed:
                        results.append(self._create_error_result(guardrail, e))

        # Merge results
        merged = GuardrailResult.merge(results)

        # Add execution metadata
        execution_time = (time.perf_counter() - start_time) * 1000
        merged.metadata.update(
            {
                "guardrail_type": guardrail_type.value,
                "guardrails_run": len(results),
                "execution_time_ms": execution_time,
            }
        )

        # Log summary
        logger.info(
            "Guardrail check completed",
            guardrail_type=guardrail_type.value,
            passed=merged.passed,
            action=merged.action.value,
            violation_count=len(merged.violations),
            execution_time_ms=execution_time,
        )

        return merged

    def _create_skip_result(self, reason: str) -> GuardrailResult:
        """Create a result for skipped guardrails."""
        return GuardrailResult(
            passed=True,
            action=GuardrailAction.ALLOW,
            risk_level=RiskLevel.NONE,
            metadata={"skipped": True, "reason": reason},
        )

    def _create_error_result(
        self,
        guardrail: BaseGuardrail,
        error: Exception | None,
    ) -> GuardrailResult:
        """Create a result for failed guardrail."""
        from yoda_foundation.guardrails.schemas import Violation

        return GuardrailResult(
            passed=False,
            action=GuardrailAction.BLOCK,
            risk_level=RiskLevel.HIGH,
            violations=[
                Violation(
                    rule_id=f"{guardrail.guardrail_id}_error",
                    rule_name=f"{guardrail.name} Error",
                    severity=RiskLevel.HIGH,
                    description=f"Guardrail execution failed: {str(error) if error else 'Unknown error'}",
                )
            ],
            guardrail_id=guardrail.guardrail_id,
            metadata={"error": str(error) if error else "Unknown error"},
        )

    def _create_timeout_result(self) -> GuardrailResult:
        """Create a result for timeout."""
        from yoda_foundation.guardrails.schemas import Violation

        return GuardrailResult(
            passed=False,
            action=GuardrailAction.BLOCK,
            risk_level=RiskLevel.HIGH,
            violations=[
                Violation(
                    rule_id="guardrail_timeout",
                    rule_name="Guardrail Timeout",
                    severity=RiskLevel.HIGH,
                    description="Guardrail execution timed out",
                )
            ],
            metadata={"timeout": True},
        )
