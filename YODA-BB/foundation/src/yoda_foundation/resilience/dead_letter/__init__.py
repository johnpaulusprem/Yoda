"""
Dead letter queue (DLQ) management for failed operations.

Provides dead letter queue management, failure analysis, and
reprocessing capabilities for resilient systems.

Example:
    ```python
    from yoda_foundation.resilience.dead_letter import (
        DLQManager,
        FailureAnalyzer,
        Reprocessor,
        DeadLetter,
    )

    # Create DLQ manager
    dlq = DLQManager(max_queue_size=10000)

    # Enqueue failed operation
    await dlq.enqueue(
        operation="process_order",
        payload={"order_id": "123"},
        error=exception,
        security_context=context,
    )

    # Analyze failures
    analyzer = FailureAnalyzer(dlq_manager=dlq)
    report = await analyzer.analyze_failure(
        operation="process_order",
        security_context=context,
    )

    # Reprocess failed items
    reprocessor = Reprocessor(dlq_manager=dlq)
    results = await reprocessor.reprocess(
        operation="process_order",
        max_items=10,
        security_context=context,
    )
    ```
"""

from yoda_foundation.resilience.dead_letter.dlq_manager import (
    DeadLetter,
    DeadLetterStatus,
    DLQManager,
)
from yoda_foundation.resilience.dead_letter.failure_analyzer import (
    FailureAnalyzer,
    FailurePattern,
    FailureReport,
)
from yoda_foundation.resilience.dead_letter.reprocessor import (
    ReprocessingResult,
    ReprocessingStrategy,
    Reprocessor,
)


__all__ = [
    # DLQ Manager
    "DLQManager",
    "DeadLetter",
    "DeadLetterStatus",
    # Failure Analyzer
    "FailureAnalyzer",
    "FailureReport",
    "FailurePattern",
    # Reprocessor
    "Reprocessor",
    "ReprocessingStrategy",
    "ReprocessingResult",
]
