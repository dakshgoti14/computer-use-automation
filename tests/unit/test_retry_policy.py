from app.errors import BusinessOutcomeError, ErrorCode, HardFailureError, RecoverableError
from app.replay.errors import RetryPolicy


def test_retries_recoverable_error_up_to_max_attempts():
    policy = RetryPolicy(max_attempts=3)
    err = RecoverableError(ErrorCode.LOCATOR_TIMEOUT_TRANSIENT, "not visible yet")
    assert policy.should_retry(err, attempt=1) is True
    assert policy.should_retry(err, attempt=2) is True
    assert policy.should_retry(err, attempt=3) is False  # bounded - never infinite


def test_never_retries_hard_failure():
    policy = RetryPolicy(max_attempts=5)
    err = HardFailureError(ErrorCode.CHECKPOINT_FAILED, "nope")
    assert policy.should_retry(err, attempt=1) is False


def test_never_retries_business_outcome():
    policy = RetryPolicy(max_attempts=5)
    err = BusinessOutcomeError(ErrorCode.MEMBER_NOT_FOUND, "not found")
    assert policy.should_retry(err, attempt=1) is False


def test_default_max_attempts_is_small_and_bounded():
    policy = RetryPolicy()
    assert 1 <= policy.max_attempts <= 5
