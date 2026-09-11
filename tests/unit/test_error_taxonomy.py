import pytest

from app.errors import (
    BusinessOutcomeError,
    ErrorCategory,
    ErrorCode,
    EscalatedError,
    HardFailureError,
    RecoverableError,
)


def test_business_outcome_error_category_and_default_retryability():
    err = BusinessOutcomeError(ErrorCode.MEMBER_NOT_FOUND, "not found")
    assert err.category == ErrorCategory.BUSINESS_OUTCOME
    assert err.retryable is False


def test_business_outcome_rejects_non_business_code():
    with pytest.raises(ValueError):
        BusinessOutcomeError(ErrorCode.CHECKPOINT_FAILED, "wrong category")


def test_recoverable_error_defaults_retryable_true():
    err = RecoverableError(ErrorCode.SESSION_TIMEOUT, "expired")
    assert err.category == ErrorCategory.RECOVERABLE
    assert err.retryable is True


def test_hard_failure_error_not_retryable():
    err = HardFailureError(ErrorCode.CHECKPOINT_FAILED, "checkpoint failed")
    assert err.category == ErrorCategory.HARD_FAILURE
    assert err.retryable is False


def test_escalated_error_carries_context_and_step_id():
    err = EscalatedError(
        ErrorCode.ACTION_BLOCKED_BY_POLICY, "blocked",
        step_id="step-05", context={"reason": "risky action"},
    )
    assert err.category == ErrorCategory.ESCALATED
    assert err.step_id == "step-05"
    assert err.context["reason"] == "risky action"


def test_to_dict_contains_required_fields():
    err = HardFailureError(ErrorCode.LOCATOR_NOT_FOUND, "gone", evidence_ref="evidence/x.jsonl")
    payload = err.to_dict()
    for key in ("category", "code", "message", "step_id", "evidence_ref", "retryable", "context"):
        assert key in payload
