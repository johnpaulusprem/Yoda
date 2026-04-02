"""
Failure analysis for dead letter queue items.

This module provides root cause analysis, failure pattern detection,
and trend analysis for failed operations.

Example:
    ```python
    from yoda_foundation.resilience.dead_letter import (
        FailureAnalyzer,
        DLQManager,
    )
    from yoda_foundation.security import create_security_context

    # Create analyzer
    dlq = DLQManager()
    analyzer = FailureAnalyzer(dlq_manager=dlq)

    # Analyze failures for operation
    report = await analyzer.analyze_failure(
        operation="process_payment",
        security_context=context,
    )

    print(f"Total failures: {report.total_failures}")
    print(f"Common errors: {report.common_errors}")

    # Categorize error
    category = await analyzer.categorize_error(
        error_type="ConnectionError",
        error_message="Database connection failed",
        security_context=context,
    )

    # Detect patterns
    patterns = await analyzer.detect_patterns(
        operation="process_payment",
        time_window_hours=24,
        security_context=context,
    )
    ```
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

from yoda_foundation.exceptions import ValidationError
from yoda_foundation.security.context import SecurityContext


if TYPE_CHECKING:
    from yoda_foundation.resilience.dead_letter.dlq_manager import DeadLetter, DLQManager

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Error categories for classification."""

    TRANSIENT = "transient"  # Temporary errors (network, timeout)
    PERMANENT = "permanent"  # Permanent errors (validation, not found)
    RESOURCE = "resource"  # Resource errors (memory, disk)
    DEPENDENCY = "dependency"  # External dependency errors
    UNKNOWN = "unknown"  # Unknown category


class FailurePattern(Enum):
    """Detected failure patterns."""

    SPIKE = "spike"  # Sudden increase in failures
    STEADY = "steady"  # Consistent failure rate
    INTERMITTENT = "intermittent"  # Sporadic failures
    CASCADING = "cascading"  # Cascading failures across operations


@dataclass
class FailureReport:
    """
    Failure analysis report.

    Attributes:
        operation: Operation name
        total_failures: Total number of failures
        time_range: Time range analyzed
        common_errors: Most common error types
        error_categories: Errors by category
        failure_rate: Failure rate per hour
        patterns: Detected failure patterns
        recommendations: Actionable recommendations
        analyzed_at: When analysis was performed

    Example:
        ```python
        report = FailureReport(
            operation="process_order",
            total_failures=150,
            common_errors={"ConnectionError": 100, "TimeoutError": 50},
            failure_rate=10.5,
            patterns=[FailurePattern.SPIKE],
        )
        ```
    """

    operation: str
    total_failures: int
    time_range: dict[str, datetime]
    common_errors: dict[str, int]
    error_categories: dict[str, int]
    failure_rate: float
    patterns: list[FailurePattern]
    recommendations: list[str] = field(default_factory=list)
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert report to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "operation": self.operation,
            "total_failures": self.total_failures,
            "time_range": {
                "start": self.time_range["start"].isoformat(),
                "end": self.time_range["end"].isoformat(),
            },
            "common_errors": self.common_errors,
            "error_categories": self.error_categories,
            "failure_rate": self.failure_rate,
            "patterns": [p.value for p in self.patterns],
            "recommendations": self.recommendations,
            "analyzed_at": self.analyzed_at.isoformat(),
            "metadata": self.metadata,
        }


class FailureAnalyzer:
    """
    Failure analyzer for dead letter queue items.

    Analyzes failed operations to identify root causes, patterns,
    and trends for proactive remediation.

    Attributes:
        dlq_manager: DLQ manager instance
        spike_threshold: Threshold for spike detection
        min_pattern_samples: Minimum samples for pattern detection

    Example:
        ```python
        # Create analyzer
        analyzer = FailureAnalyzer(
            dlq_manager=dlq,
            spike_threshold=2.0,
        )

        # Analyze operation failures
        report = await analyzer.analyze_failure(
            operation="send_notification",
            time_window_hours=24,
            security_context=context,
        )

        # Check for patterns
        if FailurePattern.SPIKE in report.patterns:
            print("Alert: Failure spike detected!")

        # Get recommendations
        for rec in report.recommendations:
            print(f"- {rec}")
        ```
    """

    def __init__(
        self,
        dlq_manager: DLQManager,
        spike_threshold: float = 2.0,
        min_pattern_samples: int = 10,
    ) -> None:
        """
        Initialize failure analyzer.

        Args:
            dlq_manager: DLQ manager instance
            spike_threshold: Spike detection threshold (multiplier)
            min_pattern_samples: Minimum samples for pattern detection

        Raises:
            ValidationError: If parameters are invalid
        """
        if spike_threshold < 1.0:
            raise ValidationError(
                message=f"spike_threshold must be at least 1.0, got {spike_threshold}",
                field_name="spike_threshold",
            )

        if min_pattern_samples < 1:
            raise ValidationError(
                message=f"min_pattern_samples must be at least 1, got {min_pattern_samples}",
                field_name="min_pattern_samples",
            )

        self.dlq_manager = dlq_manager
        self.spike_threshold = spike_threshold
        self.min_pattern_samples = min_pattern_samples

        # Error category mappings
        self._error_categories: dict[str, ErrorCategory] = {
            "ConnectionError": ErrorCategory.TRANSIENT,
            "TimeoutError": ErrorCategory.TRANSIENT,
            "TemporaryError": ErrorCategory.TRANSIENT,
            "NetworkError": ErrorCategory.TRANSIENT,
            "ValidationError": ErrorCategory.PERMANENT,
            "NotFoundError": ErrorCategory.PERMANENT,
            "AuthenticationError": ErrorCategory.PERMANENT,
            "MemoryError": ErrorCategory.RESOURCE,
            "DiskFullError": ErrorCategory.RESOURCE,
            "QuotaExceededError": ErrorCategory.RESOURCE,
            "APIError": ErrorCategory.DEPENDENCY,
            "ServiceUnavailableError": ErrorCategory.DEPENDENCY,
        }

    async def analyze_failure(
        self,
        operation: str,
        security_context: SecurityContext,
        time_window_hours: int = 24,
    ) -> FailureReport:
        """
        Analyze failures for an operation.

        Args:
            operation: Operation name
            security_context: Security context
            time_window_hours: Time window for analysis

        Returns:
            Failure analysis report

        Example:
            ```python
            # Analyze last 24 hours
            report = await analyzer.analyze_failure(
                operation="process_order",
                time_window_hours=24,
                security_context=context,
            )

            if report.total_failures > 100:
                await send_alert(report)
            ```
        """
        security_context.require_permission("resilience.read_dead_letter")

        # Get items for operation
        items = await self.dlq_manager.list_items(
            security_context=security_context,
            operation=operation,
        )

        # Filter by time window
        cutoff = datetime.now(UTC) - timedelta(hours=time_window_hours)
        recent_items = [item for item in items if item.enqueued_at >= cutoff]

        if not recent_items:
            return FailureReport(
                operation=operation,
                total_failures=0,
                time_range={"start": cutoff, "end": datetime.now(UTC)},
                common_errors={},
                error_categories={},
                failure_rate=0.0,
                patterns=[],
            )

        # Analyze errors
        error_counts = Counter(item.error_type for item in recent_items)
        common_errors = dict(error_counts.most_common(10))

        # Categorize errors
        category_counts = defaultdict(int)
        for item in recent_items:
            category = await self.categorize_error(
                error_type=item.error_type,
                error_message=item.error_message,
                security_context=security_context,
            )
            category_counts[category.value] += 1

        # Calculate failure rate
        failure_rate = len(recent_items) / time_window_hours

        # Detect patterns
        patterns = await self.detect_patterns(
            operation=operation,
            items=recent_items,
            time_window_hours=time_window_hours,
            security_context=security_context,
        )

        # Generate recommendations
        recommendations = await self._generate_recommendations(
            operation=operation,
            common_errors=common_errors,
            error_categories=dict(category_counts),
            patterns=patterns,
        )

        report = FailureReport(
            operation=operation,
            total_failures=len(recent_items),
            time_range={
                "start": cutoff,
                "end": datetime.now(UTC),
            },
            common_errors=common_errors,
            error_categories=dict(category_counts),
            failure_rate=failure_rate,
            patterns=patterns,
            recommendations=recommendations,
        )

        logger.info(
            f"Analyzed failures for '{operation}'",
            extra={
                "operation": operation,
                "total_failures": report.total_failures,
                "failure_rate": report.failure_rate,
                "patterns": [p.value for p in patterns],
            },
        )

        return report

    async def categorize_error(
        self,
        error_type: str,
        error_message: str,
        security_context: SecurityContext,
    ) -> ErrorCategory:
        """
        Categorize an error.

        Args:
            error_type: Error type name
            error_message: Error message
            security_context: Security context

        Returns:
            Error category

        Example:
            ```python
            category = await analyzer.categorize_error(
                error_type="ConnectionError",
                error_message="Connection refused",
                security_context=context,
            )

            if category == ErrorCategory.TRANSIENT:
                print("Transient error - retry recommended")
            ```
        """
        security_context.require_permission("resilience.read_dead_letter")

        # Check exact match
        if error_type in self._error_categories:
            return self._error_categories[error_type]

        # Check message patterns for transient errors
        transient_patterns = [
            "timeout",
            "connection",
            "network",
            "temporary",
            "unavailable",
            "retry",
        ]
        message_lower = error_message.lower()
        if any(pattern in message_lower for pattern in transient_patterns):
            return ErrorCategory.TRANSIENT

        # Check for resource errors
        resource_patterns = ["memory", "disk", "quota", "limit"]
        if any(pattern in message_lower for pattern in resource_patterns):
            return ErrorCategory.RESOURCE

        # Check for dependency errors
        dependency_patterns = ["api", "service", "external"]
        if any(pattern in message_lower for pattern in dependency_patterns):
            return ErrorCategory.DEPENDENCY

        # Default to unknown
        return ErrorCategory.UNKNOWN

    async def detect_patterns(
        self,
        operation: str,
        security_context: SecurityContext,
        time_window_hours: int = 24,
        items: list[DeadLetter] | None = None,
    ) -> list[FailurePattern]:
        """
        Detect failure patterns.

        Args:
            operation: Operation name
            security_context: Security context
            time_window_hours: Time window for analysis
            items: Optional pre-fetched items

        Returns:
            List of detected patterns

        Example:
            ```python
            patterns = await analyzer.detect_patterns(
                operation="process_payment",
                time_window_hours=24,
                security_context=context,
            )

            if FailurePattern.CASCADING in patterns:
                await trigger_incident_response()
            ```
        """
        security_context.require_permission("resilience.read_dead_letter")

        # Get items if not provided
        if items is None:
            all_items = await self.dlq_manager.list_items(
                security_context=security_context,
                operation=operation,
            )
            cutoff = datetime.now(UTC) - timedelta(hours=time_window_hours)
            items = [item for item in all_items if item.enqueued_at >= cutoff]

        if len(items) < self.min_pattern_samples:
            return []

        patterns = []

        # Detect spike: recent failures significantly higher than average
        hourly_failures = self._group_by_hour(items)
        if hourly_failures:
            avg_failures = sum(hourly_failures.values()) / len(hourly_failures)
            recent_hour_failures = list(hourly_failures.values())[-1] if hourly_failures else 0

            if recent_hour_failures > avg_failures * self.spike_threshold:
                patterns.append(FailurePattern.SPIKE)

        # Detect steady: consistent failure rate
        if hourly_failures:
            values = list(hourly_failures.values())
            if len(values) >= 3:
                variance = sum((x - sum(values) / len(values)) ** 2 for x in values) / len(values)
                if variance < (sum(values) / len(values)) * 0.2:  # Low variance
                    patterns.append(FailurePattern.STEADY)

        # Detect intermittent: gaps between failures
        if len(items) >= 5:
            timestamps = sorted(item.enqueued_at for item in items)
            gaps = []
            for i in range(1, len(timestamps)):
                gap = (timestamps[i] - timestamps[i - 1]).total_seconds()
                gaps.append(gap)

            avg_gap = sum(gaps) / len(gaps)
            max_gap = max(gaps)

            if max_gap > avg_gap * 3:  # Large gaps
                patterns.append(FailurePattern.INTERMITTENT)

        return patterns

    def _group_by_hour(self, items: list[DeadLetter]) -> dict[datetime, int]:
        """
        Group items by hour.

        Args:
            items: List of dead letters

        Returns:
            Dictionary of hour -> count
        """
        hourly_counts: dict[datetime, int] = defaultdict(int)

        for item in items:
            hour = item.enqueued_at.replace(minute=0, second=0, microsecond=0)
            hourly_counts[hour] += 1

        return dict(hourly_counts)

    async def _generate_recommendations(
        self,
        operation: str,
        common_errors: dict[str, int],
        error_categories: dict[str, int],
        patterns: list[FailurePattern],
    ) -> list[str]:
        """
        Generate actionable recommendations.

        Args:
            operation: Operation name
            common_errors: Common error types
            error_categories: Error categories
            patterns: Detected patterns

        Returns:
            List of recommendations
        """
        recommendations = []

        # Recommendations based on error categories
        if error_categories.get(ErrorCategory.TRANSIENT.value, 0) > 0:
            recommendations.append(
                "Transient errors detected - consider increasing retry attempts with exponential backoff"
            )

        if error_categories.get(ErrorCategory.RESOURCE.value, 0) > 0:
            recommendations.append(
                "Resource errors detected - review resource limits and scaling policies"
            )

        if error_categories.get(ErrorCategory.DEPENDENCY.value, 0) > 0:
            recommendations.append(
                "External dependency errors detected - implement circuit breaker pattern"
            )

        if error_categories.get(ErrorCategory.PERMANENT.value, 0) > 0:
            recommendations.append(
                "Permanent errors detected - review input validation and error handling"
            )

        # Recommendations based on patterns
        if FailurePattern.SPIKE in patterns:
            recommendations.append(
                "Failure spike detected - investigate recent changes and system health"
            )

        if FailurePattern.STEADY in patterns:
            recommendations.append(
                "Consistent failure rate detected - systematic issue may require architectural review"
            )

        if FailurePattern.CASCADING in patterns:
            recommendations.append(
                "Cascading failures detected - implement bulkhead pattern to isolate failures"
            )

        # Common error recommendations
        if "TimeoutError" in common_errors:
            recommendations.append(
                "Frequent timeouts - review timeout configurations and system performance"
            )

        if "ConnectionError" in common_errors:
            recommendations.append(
                "Connection errors - verify network connectivity and connection pool settings"
            )

        return recommendations

    async def get_trend_analysis(
        self,
        operation: str,
        security_context: SecurityContext,
        days: int = 7,
    ) -> dict[str, Any]:
        """
        Get failure trend analysis over time.

        Args:
            operation: Operation name
            security_context: Security context
            days: Number of days to analyze

        Returns:
            Trend analysis data

        Example:
            ```python
            trends = await analyzer.get_trend_analysis(
                operation="process_order",
                days=7,
                security_context=context,
            )

            print(f"Daily failures: {trends['daily_counts']}")
            print(f"Trend: {trends['trend']}")
            ```
        """
        security_context.require_permission("resilience.read_dead_letter")

        # Get items
        items = await self.dlq_manager.list_items(
            security_context=security_context,
            operation=operation,
        )

        # Filter by time range
        cutoff = datetime.now(UTC) - timedelta(days=days)
        recent_items = [item for item in items if item.enqueued_at >= cutoff]

        # Group by day
        daily_counts: dict[str, int] = defaultdict(int)
        for item in recent_items:
            day = item.enqueued_at.date().isoformat()
            daily_counts[day] += 1

        # Determine trend
        if len(daily_counts) >= 2:
            values = list(daily_counts.values())
            first_half = sum(values[: len(values) // 2]) / (len(values) // 2)
            second_half = sum(values[len(values) // 2 :]) / (len(values) - len(values) // 2)

            if second_half > first_half * 1.2:
                trend = "increasing"
            elif second_half < first_half * 0.8:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "operation": operation,
            "days_analyzed": days,
            "total_failures": len(recent_items),
            "daily_counts": dict(daily_counts),
            "trend": trend,
            "avg_daily_failures": len(recent_items) / days if days > 0 else 0,
        }
