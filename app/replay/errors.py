"""Replay-specific retry policy.

Retries are explicit and bounded - never infinite, never applied to actions
the error taxonomy hasn't classified as recoverable, and never applied to a
risky/irreversible action (those are blocked by the safety policy before
they would ever reach a retry loop).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.errors import AutomationError, ErrorCategory


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2

    def should_retry(self, error: AutomationError, attempt: int) -> bool:
        if attempt >= self.max_attempts:
            return False
        if error.category != ErrorCategory.RECOVERABLE:
            return False
        return error.retryable
