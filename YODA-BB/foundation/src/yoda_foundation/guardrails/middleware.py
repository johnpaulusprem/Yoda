"""
Middleware integration for guardrails.

This module provides middleware and decorators for integrating
guardrails into agent execution flows.

Example:
    ```python
    from yoda_foundation.guardrails.middleware import (
        GuardrailMiddleware,
        guarded,
    )

    # Create middleware
    middleware = GuardrailMiddleware(engine)

    # Wrap agent execution
    result = await middleware.wrap_execution(
        func=agent.run,
        input_content=user_message,
        security_context=ctx,
    )

    # Or use decorator
    @guarded(engine, check_input=True, check_output=True)
    async def process_message(message: str, security_context: SecurityContext):
        return await agent.run(message)
    ```
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

from yoda_foundation.guardrails.engine import GuardrailEngine
from yoda_foundation.guardrails.schemas import (
    GuardrailAction,
    GuardrailResult,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)

# Type variables for generic function signatures
P = ParamSpec("P")
T = TypeVar("T")


class GuardrailMiddleware:
    """
    Middleware for wrapping agent execution with guardrails.

    Provides automatic input/output checking and can modify
    or block content as needed.

    Attributes:
        engine: GuardrailEngine instance
        check_input: Whether to check input
        check_output: Whether to check output
        on_block: Callback when content is blocked
        on_modify: Callback when content is modified

    Example:
        ```python
        middleware = GuardrailMiddleware(
            engine=engine,
            check_input=True,
            check_output=True,
        )

        # Wrap a function
        result = await middleware.wrap_execution(
            func=process_message,
            input_content=user_input,
            security_context=ctx,
        )

        # Or use as context manager
        async with middleware.guarded_context(user_input, ctx) as guarded:
            if guarded.input_result.passed:
                output = await process(guarded.input_content)
                guarded.set_output(output)
        ```
    """

    def __init__(
        self,
        engine: GuardrailEngine,
        check_input: bool = True,
        check_output: bool = True,
        on_block: Callable[[GuardrailResult], Awaitable[Any]] | None = None,
        on_modify: Callable[[str, GuardrailResult], Awaitable[str]] | None = None,
    ) -> None:
        """
        Initialize the guardrail middleware.

        Args:
            engine: GuardrailEngine instance
            check_input: Whether to check input
            check_output: Whether to check output
            on_block: Callback when content is blocked
            on_modify: Callback when content is modified
        """
        self.engine = engine
        self.check_input = check_input
        self.check_output = check_output
        self.on_block = on_block
        self.on_modify = on_modify

    async def wrap_execution(
        self,
        func: Callable[..., Awaitable[str]],
        input_content: str,
        security_context: SecurityContext,
        *args: Any,
        **kwargs: Any,
    ) -> GuardedExecutionResult:
        """
        Wrap a function with guardrail checks.

        Args:
            func: Async function to wrap
            input_content: Input content to check
            security_context: Security context
            *args: Additional function arguments
            **kwargs: Additional function keyword arguments

        Returns:
            GuardedExecutionResult with execution details

        Example:
            ```python
            result = await middleware.wrap_execution(
                func=agent.run,
                input_content=user_message,
                security_context=ctx,
            )

            if result.blocked:
                return error_response(result.block_reason)

            return result.output
            ```
        """
        result = GuardedExecutionResult()
        result.input_content = input_content

        # Check input
        if self.check_input:
            input_result = await self.engine.check_input(
                content=input_content,
                security_context=security_context,
            )
            result.input_result = input_result

            if input_result.action == GuardrailAction.BLOCK:
                result.blocked = True
                result.block_reason = "Input blocked by guardrails"
                result.block_result = input_result

                if self.on_block:
                    await self.on_block(input_result)

                return result

            elif input_result.action == GuardrailAction.MODIFY:
                if input_result.modified_content:
                    input_content = input_result.modified_content
                    result.input_content = input_content

                    if self.on_modify:
                        input_content = await self.on_modify(input_content, input_result)
                        result.input_content = input_content

        # Execute function
        try:
            output = await func(input_content, *args, **kwargs)
            result.output = output
            result.executed = True
        except BaseException as e:
            result.error = e
            logger.error(f"Execution failed: {e}")
            raise

        # Check output
        if self.check_output and result.output:
            output_result = await self.engine.check_output(
                content=result.output,
                security_context=security_context,
            )
            result.output_result = output_result

            if output_result.action == GuardrailAction.BLOCK:
                result.blocked = True
                result.block_reason = "Output blocked by guardrails"
                result.block_result = output_result

                if self.on_block:
                    await self.on_block(output_result)

                return result

            elif output_result.action == GuardrailAction.MODIFY:
                if output_result.modified_content:
                    result.output = output_result.modified_content

                    if self.on_modify:
                        result.output = await self.on_modify(result.output, output_result)

        return result

    def guarded_context(
        self,
        input_content: str,
        security_context: SecurityContext,
    ) -> GuardedContext:
        """
        Create a guarded context for manual control.

        Args:
            input_content: Input content
            security_context: Security context

        Returns:
            GuardedContext async context manager

        Example:
            ```python
            async with middleware.guarded_context(input, ctx) as guarded:
                if guarded.input_result.passed:
                    output = await process(guarded.input_content)
                    guarded.set_output(output)

            if guarded.result.blocked:
                handle_blocked()
            ```
        """
        return GuardedContext(
            middleware=self,
            input_content=input_content,
            security_context=security_context,
        )


class GuardedExecutionResult:
    """
    Result of a guarded execution.

    Attributes:
        input_content: Original or modified input
        output: Execution output
        input_result: Input guardrail result
        output_result: Output guardrail result
        blocked: Whether content was blocked
        block_reason: Reason for blocking
        block_result: GuardrailResult that caused block
        executed: Whether function was executed
        error: Any execution error
    """

    def __init__(self) -> None:
        """Initialize the result."""
        self.input_content: str | None = None
        self.output: str | None = None
        self.input_result: GuardrailResult | None = None
        self.output_result: GuardrailResult | None = None
        self.blocked: bool = False
        self.block_reason: str | None = None
        self.block_result: GuardrailResult | None = None
        self.executed: bool = False
        self.error: Exception | None = None

    @property
    def passed(self) -> bool:
        """Check if execution passed all guardrails."""
        return not self.blocked and self.executed

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "executed": self.executed,
            "input_passed": self.input_result.passed if self.input_result else None,
            "output_passed": self.output_result.passed if self.output_result else None,
            "has_error": self.error is not None,
        }


class GuardedContext:
    """
    Async context manager for guarded execution.

    Provides fine-grained control over guardrail checks
    in a context manager pattern.

    Example:
        ```python
        async with GuardedContext(middleware, input, ctx) as guarded:
            if guarded.input_result.passed:
                # Safe to process
                output = await process(guarded.input_content)
                guarded.set_output(output)

        # Check final result
        if not guarded.result.blocked:
            return guarded.result.output
        ```
    """

    def __init__(
        self,
        middleware: GuardrailMiddleware,
        input_content: str,
        security_context: SecurityContext,
    ) -> None:
        """
        Initialize the guarded context.

        Args:
            middleware: GuardrailMiddleware instance
            input_content: Input content
            security_context: Security context
        """
        self.middleware = middleware
        self._input_content = input_content
        self._security_context = security_context
        self._result = GuardedExecutionResult()
        self._result.input_content = input_content

    @property
    def input_content(self) -> str:
        """Get the (possibly modified) input content."""
        return self._result.input_content or self._input_content

    @property
    def input_result(self) -> GuardrailResult | None:
        """Get the input guardrail result."""
        return self._result.input_result

    @property
    def result(self) -> GuardedExecutionResult:
        """Get the execution result."""
        return self._result

    def set_output(self, output: str) -> None:
        """
        Set the output content.

        Args:
            output: Output content

        Example:
            ```python
            async with guarded_context as guarded:
                result = await process(guarded.input_content)
                guarded.set_output(result)
            ```
        """
        self._result.output = output
        self._result.executed = True

    async def __aenter__(self) -> GuardedContext:
        """Enter the context and check input."""
        if self.middleware.check_input:
            input_result = await self.middleware.engine.check_input(
                content=self._input_content,
                security_context=self._security_context,
            )
            self._result.input_result = input_result

            if input_result.action == GuardrailAction.BLOCK:
                self._result.blocked = True
                self._result.block_reason = "Input blocked by guardrails"
                self._result.block_result = input_result
            elif input_result.action == GuardrailAction.MODIFY:
                if input_result.modified_content:
                    self._result.input_content = input_result.modified_content

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the context and check output."""
        if exc_val:
            self._result.error = exc_val
            return

        if self._result.blocked:
            return

        if self.middleware.check_output and self._result.output:
            output_result = await self.middleware.engine.check_output(
                content=self._result.output,
                security_context=self._security_context,
            )
            self._result.output_result = output_result

            if output_result.action == GuardrailAction.BLOCK:
                self._result.blocked = True
                self._result.block_reason = "Output blocked by guardrails"
                self._result.block_result = output_result
            elif output_result.action == GuardrailAction.MODIFY:
                if output_result.modified_content:
                    self._result.output = output_result.modified_content


def guarded(
    engine: GuardrailEngine,
    check_input: bool = True,
    check_output: bool = True,
    input_arg: str = "content",
    output_transform: Callable[[Any], str] | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """
    Decorator to apply guardrails to a function.

    Args:
        engine: GuardrailEngine instance
        check_input: Whether to check input
        check_output: Whether to check output
        input_arg: Name of the input argument to check
        output_transform: Function to transform output to string

    Returns:
        Decorated function

    Example:
        ```python
        @guarded(engine, check_input=True, check_output=True)
        async def process_message(
            content: str,
            security_context: SecurityContext,
        ) -> str:
            return await agent.run(content)

        # Usage
        result = await process_message(
            content=user_input,
            security_context=ctx,
        )
        ```
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Extract input content
            input_content = kwargs.get(input_arg)
            if input_content is None:
                # Try to find in positional args
                import inspect

                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if input_arg in params:
                    idx = params.index(input_arg)
                    if idx < len(args):
                        input_content = args[idx]

            # Extract security context
            security_context = kwargs.get("security_context")
            if security_context is None:
                for arg in args:
                    if isinstance(arg, SecurityContext):
                        security_context = arg
                        break

            # Check input
            if check_input and input_content and security_context:
                input_result = await engine.check_input(
                    content=str(input_content),
                    security_context=security_context,
                )

                if input_result.action == GuardrailAction.BLOCK:
                    from yoda_foundation.exceptions.guardrails import (
                        ContentBlockedError,
                    )

                    raise ContentBlockedError(
                        message="Input blocked by guardrails",
                        violations=input_result.violations,
                    )

                if input_result.action == GuardrailAction.MODIFY:
                    if input_result.modified_content:
                        kwargs[input_arg] = input_result.modified_content

            # Call function
            result = await func(*args, **kwargs)

            # Check output
            if check_output and result and security_context:
                output_content = output_transform(result) if output_transform else str(result)

                output_result = await engine.check_output(
                    content=output_content,
                    security_context=security_context,
                )

                if output_result.action == GuardrailAction.BLOCK:
                    from yoda_foundation.exceptions.guardrails import (
                        ContentBlockedError,
                    )

                    raise ContentBlockedError(
                        message="Output blocked by guardrails",
                        violations=output_result.violations,
                    )

                # Note: Modifying output is more complex and depends on return type

            return result

        return wrapper

    return decorator


class GuardrailChain:
    """
    Chain multiple guardrail engines for layered protection.

    Allows running content through multiple engines sequentially,
    with early exit on block.

    Example:
        ```python
        chain = GuardrailChain()
        chain.add(safety_engine)
        chain.add(policy_engine)
        chain.add(compliance_engine)

        result = await chain.check(content, security_context)
        ```
    """

    def __init__(self) -> None:
        """Initialize the guardrail chain."""
        self.engines: list[GuardrailEngine] = []

    def add(self, engine: GuardrailEngine) -> GuardrailChain:
        """
        Add an engine to the chain.

        Args:
            engine: GuardrailEngine to add

        Returns:
            Self for chaining
        """
        self.engines.append(engine)
        return self

    async def check_input(
        self,
        content: str,
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Check input through all engines in chain.

        Args:
            content: Content to check
            security_context: Security context

        Returns:
            Merged GuardrailResult
        """
        results: list[GuardrailResult] = []

        for engine in self.engines:
            result = await engine.check_input(content, security_context)
            results.append(result)

            # Early exit on block
            if result.action == GuardrailAction.BLOCK:
                break

            # Use modified content for next engine
            if result.modified_content:
                content = result.modified_content

        return GuardrailResult.merge(results)

    async def check_output(
        self,
        content: str,
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Check output through all engines in chain.

        Args:
            content: Content to check
            security_context: Security context

        Returns:
            Merged GuardrailResult
        """
        results: list[GuardrailResult] = []

        for engine in self.engines:
            result = await engine.check_output(content, security_context)
            results.append(result)

            if result.action == GuardrailAction.BLOCK:
                break

            if result.modified_content:
                content = result.modified_content

        return GuardrailResult.merge(results)
