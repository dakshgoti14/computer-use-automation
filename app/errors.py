"""Shared error taxonomy used across the agent, replay, and safety layers.

Every failure in this system is one of four categories (see REPORT.md,
"Determinism & error handling" for the rationale):

* ``BUSINESS_OUTCOME``  - the target application legitimately reported a
  negative-but-expected result (e.g. member not found). Not a bug.
* ``RECOVERABLE``       - a transient condition (session timeout, slow
  render) that a bounded retry policy may resolve.
* ``HARD_FAILURE``      - something the system cannot safely proceed past
  (checkpoint failure after retries, corrupt artifact, unsupported action).
* ``ESCALATED``         - automation deliberately stopped and handed control
  to a human operator.

Nothing in this codebase should ``raise Exception("...")``. Every raised
error is an :class:`AutomationError` (or subclass) carrying a stable code,
category, retryability, the step it occurred on, and a pointer to evidence.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    BUSINESS_OUTCOME = "business_outcome"
    RECOVERABLE = "recoverable"
    HARD_FAILURE = "hard_failure"
    ESCALATED = "escalated"


class ErrorCode(str, Enum):
    """Stable, machine-checkable error codes.

    Stability matters: these codes are persisted in evidence and artifacts'
    ``error_mapping`` and must not be renamed casually.
    """

    # Business outcomes
    MEMBER_NOT_FOUND = "MEMBER_NOT_FOUND"
    NO_RESULTS = "NO_RESULTS"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"

    # Recoverable conditions
    SESSION_TIMEOUT = "SESSION_TIMEOUT"
    TRANSIENT_LOAD_STATE = "TRANSIENT_LOAD_STATE"
    LOCATOR_TIMEOUT_TRANSIENT = "LOCATOR_TIMEOUT_TRANSIENT"

    # Hard failures
    CHECKPOINT_FAILED = "CHECKPOINT_FAILED"
    LOCATOR_NOT_FOUND = "LOCATOR_NOT_FOUND"
    UNEXPECTED_APPLICATION_ERROR = "UNEXPECTED_APPLICATION_ERROR"
    ARTIFACT_INVALID = "ARTIFACT_INVALID"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    OUTPUT_CONVERSION_FAILED = "OUTPUT_CONVERSION_FAILED"
    PARAMETER_RESOLUTION_FAILED = "PARAMETER_RESOLUTION_FAILED"
    MALFORMED_VALUE = "MALFORMED_VALUE"
    INTERNAL_REPLAY_ERROR = "INTERNAL_REPLAY_ERROR"

    # Safety
    ACTION_BLOCKED_BY_POLICY = "ACTION_BLOCKED_BY_POLICY"
    DOMAIN_NOT_ALLOWED = "DOMAIN_NOT_ALLOWED"

    # Escalation / session
    ESCALATION_REQUESTED = "ESCALATION_REQUESTED"
    SESSION_UNDER_HUMAN_CONTROL = "SESSION_UNDER_HUMAN_CONTROL"
    SESSION_ALREADY_CONTROLLED = "SESSION_ALREADY_CONTROLLED"

    # Agent / provider
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    LLM_CONFIG_MISSING = "LLM_CONFIG_MISSING"
    MAX_STEPS_EXCEEDED = "MAX_STEPS_EXCEEDED"
    INVALID_AGENT_DECISION = "INVALID_AGENT_DECISION"


#: Codes that a bounded retry policy is permitted to retry.
RETRYABLE_CODES = frozenset(
    {
        ErrorCode.SESSION_TIMEOUT,
        ErrorCode.TRANSIENT_LOAD_STATE,
        ErrorCode.LOCATOR_TIMEOUT_TRANSIENT,
    }
)

#: Codes that represent an expected business result, not a defect.
BUSINESS_OUTCOME_CODES = frozenset(
    {
        ErrorCode.MEMBER_NOT_FOUND,
        ErrorCode.NO_RESULTS,
        ErrorCode.VALIDATION_REJECTED,
    }
)


class AutomationError(Exception):
    """Base class for every typed error raised by this system.

    Attributes mirror the fields required by the assignment: category,
    stable code, human message, the step it happened on, an evidence
    pointer, whether it is retryable, and free-form context (already
    redaction-safe - callers must not put raw secrets in ``context``).
    """

    category: ErrorCategory = ErrorCategory.HARD_FAILURE

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        step_id: str | None = None,
        evidence_ref: str | None = None,
        retryable: bool | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.step_id = step_id
        self.evidence_ref = evidence_ref
        self.retryable = retryable if retryable is not None else code in RETRYABLE_CODES
        self.context = context or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "code": self.code.value,
            "message": self.message,
            "step_id": self.step_id,
            "evidence_ref": self.evidence_ref,
            "retryable": self.retryable,
            "context": self.context,
        }


class BusinessOutcomeError(AutomationError):
    """The application returned an expected negative result (not a bug)."""

    category = ErrorCategory.BUSINESS_OUTCOME

    def __init__(self, code: ErrorCode, message: str, **kwargs: Any) -> None:
        if code not in BUSINESS_OUTCOME_CODES:
            raise ValueError(f"{code} is not a registered business-outcome code")
        kwargs.setdefault("retryable", False)
        super().__init__(code, message, **kwargs)


class RecoverableError(AutomationError):
    """A transient condition a bounded retry policy may resolve."""

    category = ErrorCategory.RECOVERABLE

    def __init__(self, code: ErrorCode, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("retryable", True)
        super().__init__(code, message, **kwargs)


class HardFailureError(AutomationError):
    """Automation cannot safely proceed; not retryable by policy."""

    category = ErrorCategory.HARD_FAILURE

    def __init__(self, code: ErrorCode, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(code, message, **kwargs)


class EscalatedError(AutomationError):
    """Automation deliberately stopped for human intervention."""

    category = ErrorCategory.ESCALATED

    def __init__(self, code: ErrorCode, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(code, message, **kwargs)
