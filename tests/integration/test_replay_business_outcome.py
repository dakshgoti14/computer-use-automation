"""A non-existent member is a BUSINESS OUTCOME, not a crash: replay must
finish cleanly with status=business_outcome and code=MEMBER_NOT_FOUND."""

from __future__ import annotations

import pytest

from app.browser.playwright_surface import PlaywrightSurface
from app.replay.executor import ReplayEngine
from app.replay.result import ReplayStatus
from app.safety.policy import SafetyPolicy
from tests.conftest import build_gold_artifact

pytestmark = pytest.mark.asyncio


async def test_nonexistent_member_is_a_clean_business_outcome(demo_app_base_url):
    artifact = build_gold_artifact(demo_app_base_url)
    surface = PlaywrightSurface(headless=True)
    policy = SafetyPolicy(allowed_domains=("127.0.0.1",))
    engine = ReplayEngine(surface, safety_policy=policy)

    try:
        result = await engine.run(artifact, {"member_id": "99999"})
    finally:
        await surface.close()

    assert result.status == ReplayStatus.BUSINESS_OUTCOME
    assert result.code == "MEMBER_NOT_FOUND"
    assert result.outputs == {}
    # A business outcome is a normal, reportable result - no exception should
    # have propagated to get here (implicit: this test would have raised
    # already if the engine threw instead of returning cleanly).
