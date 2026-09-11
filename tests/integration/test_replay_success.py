"""End-to-end (against the real demo app + real Chromium) proof that
deterministic replay succeeds, extracts a typed money output, and passes
every checkpoint - without any LLM in the loop."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.browser.playwright_surface import PlaywrightSurface
from app.observability.evidence import EvidenceWriter
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


async def test_replay_screenshots_are_opt_in(demo_app_base_url, tmp_path):
    """Per-step screenshots exist purely to let a human *see* the browser
    driving the real UI (the public demo page's whole reason for being) -
    they must never appear unasked-for and bloat every ordinary replay/
    benchmark evidence directory with 8 PNGs nobody requested."""

    artifact = build_gold_artifact(demo_app_base_url)
    policy = SafetyPolicy(allowed_domains=("127.0.0.1",))

    # Default: no evidence writer even wired up, matching how
    # scripts/replay_capability.py and the benchmark script actually call
    # this today - screenshots must not be silently expected.
    surface = PlaywrightSurface(headless=True)
    engine = ReplayEngine(surface, safety_policy=policy)
    try:
        result = await engine.run(artifact, {"member_id": "12345"})
    finally:
        await surface.close()
    assert all(step.screenshot_ref is None for step in result.steps)

    # Opted in: every step outcome carries a real screenshot file.
    surface = PlaywrightSurface(headless=True)
    evidence = EvidenceWriter(evidence_root=tmp_path, run_kind="replay", run_id="with-screens")
    engine = ReplayEngine(surface, safety_policy=policy, evidence=evidence, capture_screenshots=True)
    try:
        result = await engine.run(artifact, {"member_id": "12345"})
    finally:
        await surface.close()

    assert result.status == ReplayStatus.SUCCESS, result.message
    assert len(result.steps) == len(artifact.steps)
    for step in result.steps:
        assert step.screenshot_ref, f"expected a screenshot for {step.step_id}"
        from pathlib import Path

        assert Path(step.screenshot_ref).exists()
