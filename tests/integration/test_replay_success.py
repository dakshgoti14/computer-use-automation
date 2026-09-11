"""End-to-end (against the real demo app + real Chromium) proof that
deterministic replay succeeds, extracts a typed money output, and passes
every checkpoint - without any LLM in the loop."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.browser.playwright_surface import PlaywrightSurface
from app.replay.executor import ReplayEngine
from app.replay.result import MoneyValue, ReplayStatus
from app.safety.policy import SafetyPolicy
from tests.conftest import build_gold_artifact

pytestmark = pytest.mark.asyncio


async def test_replay_succeeds_and_extracts_typed_savings_balance(demo_app_base_url):
    artifact = build_gold_artifact(demo_app_base_url)
    surface = PlaywrightSurface(headless=True)
    policy = SafetyPolicy(allowed_domains=("127.0.0.1",))
    engine = ReplayEngine(surface, safety_policy=policy)

    try:
        result = await engine.run(artifact, {"member_id": "12345"})
    finally:
        await surface.close()

    assert result.status == ReplayStatus.SUCCESS, result.message
    assert result.code is None
    balance = result.outputs["savings_balance"]
    assert isinstance(balance, MoneyValue)
    assert balance.amount == Decimal("4231.55")
    assert all(c.passed for step in result.steps for c in step.checkpoints)
    assert len(result.steps) == len(artifact.steps)


async def test_replay_is_reusable_across_different_member_ids(demo_app_base_url):
    """The SAME artifact, unmodified, replayed with a different parameter -
    proves the capability is genuinely parameterized, not hard-coded to
    "12345"."""

    artifact = build_gold_artifact(demo_app_base_url)
    surface = PlaywrightSurface(headless=True)
    policy = SafetyPolicy(allowed_domains=("127.0.0.1",))
    engine = ReplayEngine(surface, safety_policy=policy)

    try:
        result = await engine.run(artifact, {"member_id": "67890"})
    finally:
        await surface.close()

    assert result.status == ReplayStatus.SUCCESS, result.message
    assert result.outputs["savings_balance"].amount == Decimal("812.00")
