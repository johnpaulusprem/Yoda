"""
Fact-checking and hallucination detection guardrails.

This module provides guardrails for verifying facts against sources
and detecting potential hallucinations in LLM outputs.

Example:
    ```python
    from yoda_foundation.guardrails.fact_check import (
        FactCheckGuardrail,
        GroundingGuardrail,
        FactCheckResult,
    )

    # Create fact-checking guardrail
    guardrail = FactCheckGuardrail()

    # Check response against sources
    result = await guardrail.verify_facts(
        content="The company was founded in 2015.",
        sources=["The company was established in 2010."],
        security_context=ctx,
    )

    if not result.verified:
        print(f"Unsupported claims: {result.unsupported_claims}")
    ```
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from yoda_foundation.guardrails.base import OutputGuardrail, RetrievalGuardrail
from yoda_foundation.guardrails.schemas import (
    ContentCategory,
    FactCheckResult,
    GuardrailAction,
    GuardrailConfig,
    GuardrailResult,
    RetrievalContext,
    RiskLevel,
    Violation,
)
from yoda_foundation.security.context import SecurityContext
from yoda_foundation.observability.logging import get_logger


logger = get_logger(__name__)


@dataclass
class Claim:
    """
    Represents an extracted claim from content.

    Attributes:
        text: The claim text
        claim_type: Type of claim (factual, opinion, etc.)
        confidence: Extraction confidence
        location: Location in original content

    Example:
        ```python
        claim = Claim(
            text="The company was founded in 2015.",
            claim_type="factual",
            confidence=0.9,
            location=(0, 35),
        )
        ```
    """

    text: str
    claim_type: str = "factual"
    confidence: float = 1.0
    location: tuple[int, int] | None = None


class FactCheckGuardrail(OutputGuardrail):
    """
    Guardrail for fact-checking content against sources.

    Extracts claims from content and verifies them against
    provided source documents.

    Attributes:
        confidence_threshold: Minimum confidence for verification
        strict_mode: Require all claims to be verified

    Example:
        ```python
        guardrail = FactCheckGuardrail(
            confidence_threshold=0.7,
            strict_mode=False,
        )

        result = await guardrail.verify_facts(
            content="Paris is the capital of France.",
            sources=["France's capital is Paris."],
            security_context=ctx,
        )
        ```
    """

    # Claim extraction patterns
    CLAIM_PATTERNS = [
        # Definitive statements
        (r"([A-Z][^.!?]*(?:is|are|was|were|has|have|had)\s+[^.!?]+[.!?])", "factual"),
        # Numerical claims
        (r"([A-Z][^.!?]*\d+[^.!?]*[.!?])", "numerical"),
        # Date claims
        (r"([A-Z][^.!?]*(?:in\s+\d{4}|on\s+\w+\s+\d+)[^.!?]*[.!?])", "temporal"),
        # Comparative claims
        (r"([A-Z][^.!?]*(?:more|less|better|worse|largest|smallest)[^.!?]*[.!?])", "comparative"),
    ]

    def __init__(
        self,
        confidence_threshold: float = 0.7,
        strict_mode: bool = False,
        guardrail_id: str | None = None,
        priority: int = 30,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the fact-check guardrail.

        Args:
            confidence_threshold: Minimum verification confidence
            strict_mode: Require all claims verified
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "fact_check_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.confidence_threshold = confidence_threshold
        self.strict_mode = strict_mode

        # Compile patterns
        self._compiled_patterns: list[tuple[re.Pattern, str]] = []
        for pattern, claim_type in self.CLAIM_PATTERNS:
            self._compiled_patterns.append((re.compile(pattern, re.MULTILINE), claim_type))

    async def verify_facts(
        self,
        content: str,
        sources: list[str],
        security_context: SecurityContext,
    ) -> FactCheckResult:
        """
        Verify facts in content against sources.

        Args:
            content: Content containing claims
            sources: Source documents for verification
            security_context: Security context

        Returns:
            FactCheckResult with verification details

        Example:
            ```python
            result = await guardrail.verify_facts(
                content="The product was launched in 2020.",
                sources=[
                    "Product launch announcement 2020",
                    "The product debuted in January 2020.",
                ],
                security_context=ctx,
            )

            if result.has_hallucinations:
                handle_hallucinations(result.unsupported_claims)
            ```
        """
        # Extract claims
        claims = self._extract_claims(content)

        if not claims:
            return FactCheckResult(
                verified=True,
                confidence=1.0,
                claims=[],
            )

        # Verify each claim against sources
        supported: list[str] = []
        unsupported: list[str] = []
        contradicted: list[str] = []

        combined_sources = " ".join(sources).lower()

        for claim in claims:
            verification = self._verify_claim(claim, combined_sources)

            if verification == "supported":
                supported.append(claim.text)
            elif verification == "contradicted":
                contradicted.append(claim.text)
            else:
                unsupported.append(claim.text)

        # Calculate overall verification status
        total_claims = len(claims)
        supported_ratio = len(supported) / total_claims if total_claims > 0 else 1.0

        verified = supported_ratio >= self.confidence_threshold
        if self.strict_mode and (unsupported or contradicted):
            verified = False

        return FactCheckResult(
            verified=verified,
            confidence=supported_ratio,
            claims=[c.text for c in claims],
            supported_claims=supported,
            unsupported_claims=unsupported,
            contradicted_claims=contradicted,
            sources_used=sources,
        )

    def _extract_claims(self, content: str) -> list[Claim]:
        """
        Extract factual claims from content.

        Args:
            content: Content to analyze

        Returns:
            List of extracted claims
        """
        claims: list[Claim] = []
        seen_texts: set[str] = set()

        for pattern, claim_type in self._compiled_patterns:
            matches = pattern.finditer(content)
            for match in matches:
                text = match.group(1).strip()

                # Skip duplicates and short claims
                if text in seen_texts or len(text) < 15:
                    continue

                seen_texts.add(text)
                claims.append(
                    Claim(
                        text=text,
                        claim_type=claim_type,
                        confidence=0.8,
                        location=(match.start(), match.end()),
                    )
                )

        return claims

    def _verify_claim(self, claim: Claim, sources: str) -> str:
        """
        Verify a single claim against sources.

        Args:
            claim: Claim to verify
            sources: Combined source text

        Returns:
            "supported", "unsupported", or "contradicted"
        """
        claim_words = set(re.findall(r"\w+", claim.text.lower()))

        # Remove common words
        common_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "has",
            "have",
            "had",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "and",
            "or",
            "but",
            "with",
        }
        claim_words -= common_words

        if not claim_words:
            return "unsupported"

        source_words = set(re.findall(r"\w+", sources))

        # Calculate overlap
        overlap = len(claim_words & source_words)
        overlap_ratio = overlap / len(claim_words) if claim_words else 0

        # Check for numerical matches
        claim_numbers = set(re.findall(r"\d+", claim.text))
        source_numbers = set(re.findall(r"\d+", sources))

        numbers_match = bool(claim_numbers & source_numbers) if claim_numbers else True

        # Determine verification status
        if overlap_ratio >= 0.6 and numbers_match:
            return "supported"
        elif claim_numbers and not numbers_match and overlap_ratio >= 0.4:
            # Numbers in claim don't match sources
            return "contradicted"
        else:
            return "unsupported"

    async def detect_hallucination(
        self,
        response: str,
        context: str,
        security_context: SecurityContext,
    ) -> FactCheckResult:
        """
        Detect hallucinations in a response given its context.

        Args:
            response: LLM response to check
            context: Context provided to the LLM
            security_context: Security context

        Returns:
            FactCheckResult with hallucination analysis

        Example:
            ```python
            result = await guardrail.detect_hallucination(
                response="The CEO said the company will expand to 50 countries.",
                context="The CEO announced plans for expansion.",
                security_context=ctx,
            )

            if result.has_hallucinations:
                print("Response contains unsupported claims")
            ```
        """
        return await self.verify_facts(response, [context], security_context)

    async def check_consistency(
        self,
        statements: list[str],
        security_context: SecurityContext,
    ) -> FactCheckResult:
        """
        Check internal consistency of multiple statements.

        Args:
            statements: List of statements to check
            security_context: Security context

        Returns:
            FactCheckResult with consistency analysis

        Example:
            ```python
            result = await guardrail.check_consistency(
                statements=[
                    "The meeting is at 2pm.",
                    "The meeting starts at 3pm.",
                ],
                security_context=ctx,
            )

            if result.contradicted_claims:
                print("Inconsistent statements found")
            ```
        """
        if len(statements) < 2:
            return FactCheckResult(
                verified=True,
                confidence=1.0,
                claims=statements,
            )

        contradicted: list[str] = []

        # Compare each pair of statements
        for i, stmt1 in enumerate(statements):
            for stmt2 in statements[i + 1 :]:
                if self._are_contradictory(stmt1, stmt2):
                    contradicted.extend([stmt1, stmt2])

        verified = len(contradicted) == 0

        return FactCheckResult(
            verified=verified,
            confidence=1.0 if verified else 0.5,
            claims=statements,
            contradicted_claims=list(set(contradicted)),
        )

    def _are_contradictory(self, stmt1: str, stmt2: str) -> bool:
        """
        Check if two statements are contradictory.

        Args:
            stmt1: First statement
            stmt2: Second statement

        Returns:
            True if statements contradict each other
        """
        # Extract numbers
        nums1 = set(re.findall(r"\d+", stmt1))
        nums2 = set(re.findall(r"\d+", stmt2))

        # If both have numbers and they're different, might be contradictory
        if nums1 and nums2 and nums1 != nums2:
            # Check if they're talking about the same thing
            words1 = set(re.findall(r"\w+", stmt1.lower()))
            words2 = set(re.findall(r"\w+", stmt2.lower()))

            overlap = len(words1 & words2) / max(len(words1), len(words2))
            if overlap > 0.5:
                return True

        # Check for negation patterns
        negation_pairs = [
            (r"is\s+(\w+)", r"is\s+not\s+\1"),
            (r"will\s+(\w+)", r"will\s+not\s+\1"),
            (r"can\s+(\w+)", r"cannot\s+\1"),
        ]

        for pos, neg in negation_pairs:
            if re.search(pos, stmt1) and re.search(neg, stmt2):
                return True
            if re.search(neg, stmt1) and re.search(pos, stmt2):
                return True

        return False

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check content for factual accuracy."""
        sources = context.get("sources", [])

        if not sources:
            # No sources to verify against
            return self._create_pass_result(no_sources=True)

        fact_check_result = await self.verify_facts(content, sources, security_context)

        if not fact_check_result.verified:
            violations: list[Violation] = []

            for claim in fact_check_result.unsupported_claims:
                violations.append(
                    self._create_violation(
                        rule_id="unsupported_claim",
                        rule_name="Unsupported Claim",
                        severity=RiskLevel.MEDIUM,
                        description="Claim not supported by sources",
                        evidence=claim[:100],
                        category=ContentCategory.HALLUCINATION,
                    )
                )

            for claim in fact_check_result.contradicted_claims:
                violations.append(
                    self._create_violation(
                        rule_id="contradicted_claim",
                        rule_name="Contradicted Claim",
                        severity=RiskLevel.HIGH,
                        description="Claim contradicted by sources",
                        evidence=claim[:100],
                        category=ContentCategory.HALLUCINATION,
                    )
                )

            return self._create_fail_result(
                violations=violations,
                action=GuardrailAction.WARN,
                risk_level=RiskLevel.HIGH
                if fact_check_result.contradicted_claims
                else RiskLevel.MEDIUM,
                fact_check_result=fact_check_result.to_dict(),
            )

        return self._create_pass_result(
            fact_check_result=fact_check_result.to_dict(),
        )


class GroundingGuardrail(RetrievalGuardrail):
    """
    Guardrail for ensuring responses are grounded in provided context.

    Verifies that LLM responses only contain information that can
    be traced back to the provided documents.

    Attributes:
        grounding_threshold: Minimum grounding ratio (0.0-1.0)

    Example:
        ```python
        guardrail = GroundingGuardrail(grounding_threshold=0.8)

        result = await guardrail.check_grounding(
            response="The policy allows 30 days return.",
            context="Return policy: 30 day returns accepted.",
            security_context=ctx,
        )

        if not result.passed:
            print("Response not properly grounded in context")
        ```
    """

    def __init__(
        self,
        grounding_threshold: float = 0.7,
        guardrail_id: str | None = None,
        priority: int = 35,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the grounding guardrail.

        Args:
            grounding_threshold: Minimum grounding ratio
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "grounding_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.grounding_threshold = grounding_threshold

    async def check_grounding(
        self,
        response: str,
        context: str,
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """
        Check if response is grounded in context.

        Args:
            response: LLM response to check
            context: Context/documents provided
            security_context: Security context

        Returns:
            GuardrailResult with grounding analysis

        Example:
            ```python
            result = await guardrail.check_grounding(
                response=llm_output,
                context=retrieved_documents,
                security_context=ctx,
            )
            ```
        """
        ctx = {
            "retrieval_context": RetrievalContext(
                query="",
                documents=[{"content": context}],
            ),
            "response": response,
        }
        return await self.check(response, ctx, security_context)

    async def _check_retrieval_impl(
        self,
        retrieval_context: RetrievalContext,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check if content is grounded in retrieved documents."""
        response = context.get("response", "")

        if not response:
            return self._create_pass_result(no_response=True)

        # Combine all document contents
        doc_contents = []
        for doc in retrieval_context.documents:
            if isinstance(doc, dict):
                doc_contents.append(doc.get("content", str(doc)))
            else:
                doc_contents.append(str(doc))

        combined_context = " ".join(doc_contents).lower()

        if not combined_context:
            return self._create_pass_result(no_context=True)

        # Calculate grounding ratio
        grounding_ratio = self._calculate_grounding(response, combined_context)

        if grounding_ratio < self.grounding_threshold:
            return self._create_fail_result(
                violations=[
                    self._create_violation(
                        rule_id="insufficient_grounding",
                        rule_name="Insufficient Grounding",
                        severity=RiskLevel.MEDIUM,
                        description=f"Response not sufficiently grounded in context (ratio: {grounding_ratio:.2f})",
                        category=ContentCategory.HALLUCINATION,
                        grounding_ratio=grounding_ratio,
                        threshold=self.grounding_threshold,
                    )
                ],
                action=GuardrailAction.WARN,
                risk_level=RiskLevel.MEDIUM,
                grounding_ratio=grounding_ratio,
            )

        return self._create_pass_result(
            grounding_ratio=grounding_ratio,
        )

    def _calculate_grounding(self, response: str, context: str) -> float:
        """
        Calculate how well response is grounded in context.

        Args:
            response: Response text
            context: Context text

        Returns:
            Grounding ratio (0.0-1.0)
        """
        # Extract meaningful words from response
        response_words = set(re.findall(r"\b\w{4,}\b", response.lower()))

        # Remove common words
        common_words = {
            "that",
            "this",
            "with",
            "from",
            "have",
            "been",
            "were",
            "will",
            "would",
            "could",
            "should",
            "about",
            "which",
            "their",
            "there",
            "these",
            "those",
            "when",
            "what",
            "where",
            "your",
            "some",
        }
        response_words -= common_words

        if not response_words:
            return 1.0  # No significant words to check

        context_words = set(re.findall(r"\b\w{4,}\b", context))

        # Calculate overlap
        grounded_words = response_words & context_words
        grounding_ratio = len(grounded_words) / len(response_words)

        return grounding_ratio


class HallucinationGuardrail(OutputGuardrail):
    """
    Guardrail specifically for detecting hallucinations.

    Combines fact-checking and grounding to detect when
    LLM outputs contain fabricated information.

    Attributes:
        fact_checker: FactCheckGuardrail instance
        grounding_checker: GroundingGuardrail instance

    Example:
        ```python
        guardrail = HallucinationGuardrail()

        result = await guardrail.check(
            content=llm_response,
            context={"sources": source_docs, "query": user_query},
            security_context=ctx,
        )

        if not result.passed:
            # Response contains potential hallucinations
            return request_rewrite(result.violations)
        ```
    """

    def __init__(
        self,
        confidence_threshold: float = 0.7,
        grounding_threshold: float = 0.7,
        guardrail_id: str | None = None,
        priority: int = 25,
        enabled: bool = True,
        config: GuardrailConfig | None = None,
    ) -> None:
        """
        Initialize the hallucination guardrail.

        Args:
            confidence_threshold: Fact-check confidence threshold
            grounding_threshold: Grounding threshold
            guardrail_id: Unique identifier
            priority: Execution priority
            enabled: Whether guardrail is active
            config: Guardrail configuration
        """
        super().__init__(
            guardrail_id=guardrail_id or "hallucination_guardrail",
            priority=priority,
            enabled=enabled,
            config=config,
        )
        self.fact_checker = FactCheckGuardrail(
            confidence_threshold=confidence_threshold,
            config=config,
        )
        self.grounding_checker = GroundingGuardrail(
            grounding_threshold=grounding_threshold,
            config=config,
        )

    async def _check_impl(
        self,
        content: str,
        context: dict[str, Any],
        security_context: SecurityContext,
    ) -> GuardrailResult:
        """Check content for hallucinations."""
        sources = context.get("sources", [])
        combined_context = context.get("context", " ".join(sources) if sources else "")

        results: list[GuardrailResult] = []

        # Run fact check if sources available
        if sources:
            fact_result = await self.fact_checker.check(
                content,
                {"sources": sources},
                security_context,
            )
            results.append(fact_result)

        # Run grounding check if context available
        if combined_context:
            grounding_result = await self.grounding_checker.check_grounding(
                content,
                combined_context,
                security_context,
            )
            results.append(grounding_result)

        if not results:
            return self._create_pass_result(no_checks_available=True)

        # Merge results
        return GuardrailResult.merge(results)
