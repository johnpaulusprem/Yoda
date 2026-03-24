"""
Bulkhead mechanisms for resource isolation.

Provides bulkhead patterns for isolating resources and preventing
cascading failures through resource exhaustion.

Example:
    ```python
    from yoda_foundation.resilience.bulkhead import (
        Bulkhead,
        SemaphoreBulkhead,
        BulkheadConfig,
    )

    # Create semaphore-based bulkhead
    bulkhead = SemaphoreBulkhead(
        name="api_calls",
        max_concurrent=10,
        max_queue_size=50,
    )

    # Execute with resource isolation
    async with bulkhead.acquire(security_context=context):
        result = await api_call()

    # Or use execute method
    result = await bulkhead.execute(
        func=api_call,
        security_context=context,
    )
    ```
"""

from yoda_foundation.resilience.bulkhead.bulkhead import (
    Bulkhead,
    BulkheadConfig,
    BulkheadStatistics,
)
from yoda_foundation.resilience.bulkhead.semaphore_bulkhead import (
    QueuedRequest,
    SemaphoreBulkhead,
)


__all__ = [
    "Bulkhead",
    "BulkheadConfig",
    "BulkheadStatistics",
    "QueuedRequest",
    "SemaphoreBulkhead",
]
