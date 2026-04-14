# k3c/universe/retry.py
"""
Retry policies and fallback strategies for Bridge delivery.

Used by BridgedUniverse to handle target delivery failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BridgeMode(StrEnum):
    """Bridge delivery mode — controls consistency guarantees."""

    SYNCHRONOUS = "synchronous"
    ASYNC = "async"
    BEST_EFFORT = "best_effort"


class FallbackStrategy(StrEnum):
    """What to do when bridge delivery fails after all retries."""

    FAIL = "fail"
    IGNORE = "ignore"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True)
class RetryPolicy:
    """Retry configuration for bridge delivery."""

    max_attempts: int = 1
    base_delay_ms: int = 0
    strategy: str = "none"

    @staticmethod
    def no_retry() -> RetryPolicy:
        return RetryPolicy(max_attempts=1, base_delay_ms=0, strategy="none")

    @staticmethod
    def fixed_delay(n: int, delay_ms: int) -> RetryPolicy:
        return RetryPolicy(max_attempts=n, base_delay_ms=delay_ms, strategy="fixed")

    @staticmethod
    def exponential_backoff(n: int, base_ms: int) -> RetryPolicy:
        return RetryPolicy(
            max_attempts=n, base_delay_ms=base_ms, strategy="exponential"
        )


@dataclass(frozen=True)
class DeadLetterEntry:
    """A failed bridge delivery stored for later inspection."""

    source_event: dict[str, object]
    target_event: dict[str, object]
    source_state: dict[str, object]
    attempts: int
    last_error: str
