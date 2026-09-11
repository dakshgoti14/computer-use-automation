"""Deterministic failure-mode demonstrations, run for real (not faked):

* an unexpected application error -> HARD_FAILURE
* a session timeout that recovers within the retry budget -> SUCCESS
* a session timeout with the retry budget set to zero-margin -> HARD_FAILURE
"""

from __future__ import annotations

import pytest

from app.browser.playwright_surface import PlaywrightSurface
from app.replay.errors import RetryPolicy
from app.replay.executor import ReplayEngine
from app.replay.result import ReplayStatus
from app.safety.policy import SafetyPolicy
from tests.conftest import build_gold_artifact

pytestmark = pytest.mark.asyncio


async def test_unexpected_application_error_is_a_hard_failure(demo_app_base_url):
    artifact = build_gold_artifact(demo_app_base_url)
    surface = PlaywrightSurface(headless=True)
    policy = SafetyPolicy(allowed_domains=("127.0.0.1",))
    engine = ReplayEngine(surface, safety_policy=policy)

    try:
        # member id 40404 triggers the demo app's simulated unexpected error.
        result = await engine.run(artifact, {"member_id": "40404"})
    finally:
        await surface.close()

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.code == "UNEXPECTED_APPLICATION_ERROR"


async def test_session_timeout_recovers_within_retry_budget(demo_app_base_url):
    artifact = build_gold_artifact(demo_app_base_url)
    surface = PlaywrightSurface(headless=True)
    policy = SafetyPolicy(allowed_domains=("127.0.0.1",))
    # Default max_attempts=2 gives the engine one full restart after the
    # forced timeout - the demo app only forces the timeout ONCE per
    # session, so the second attempt succeeds for real.
    engine = ReplayEngine(surface, safety_policy=policy, retry_policy=RetryPolicy(max_attempts=2))

    try:
        result = await engine.run(artifact, {"member_id": "50000"})
    finally:
        await surface.close()

    assert result.status == ReplayStatus.SUCCESS, result.message
    assert result.total_retries >= 1


async def test_session_timeout_exhausts_bounded_retries_and_hard_fails(demo_app_base_url):
    artifact = build_gold_artifact(demo_app_base_url)
    surface = PlaywrightSurface(headless=True)
    policy = SafetyPolicy(allowed_domains=("127.0.0.1",))
    # max_attempts=1: the engine must not even attempt a retry - proves
    # retries are bounded, never open-ended.
    engine = ReplayEngine(surface, safety_policy=policy, retry_policy=RetryPolicy(max_attempts=1))

    try:
        result = await engine.run(artifact, {"member_id": "50000"})
    finally:
        await surface.close()

    assert result.status == ReplayStatus.HARD_FAILURE
    assert result.code == "SESSION_TIMEOUT"
