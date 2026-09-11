"""End-to-end proof of the full lifecycle the assignment describes:

    goal -> DiscoveryEngine (LLM) -> CapabilityArtifact -> disk -> reload
         -> ReplayEngine (no LLM) -> typed output

Unlike tests/integration/*, which exercise each stage in relative isolation,
this test chains discovery's OWN output (not a hand-built fixture) into the
replay engine, proving the two stages are genuinely compatible end to end -
using a scripted provider so it stays fast, free, and deterministic. The
one-time genuine Gemini run is scripts/discover_capability.py (see README).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.agent.loop import DiscoveryEngine, DiscoveryStatus
from app.agent.models import ActionType, AgentDecision, LocatorTargetInput
from app.agent.planner import Planner
from app.artifacts.schema import OutputSpec, ParameterSpec, ParamType
from app.artifacts.store import ArtifactStore
from app.browser.playwright_surface import PlaywrightSurface
from app.observability.evidence import EvidenceWriter
from app.providers.mock import CountingLLMProvider, ScriptedLLMProvider
from app.replay.executor import ReplayEngine
from app.replay.result import MoneyValue, ReplayStatus
from app.safety.policy import SafetyPolicy

pytestmark = pytest.mark.asyncio


def _decision(action: ActionType, **kwargs) -> AgentDecision:
    return AgentDecision(action=action, reasoning="e2e scripted step", **kwargs)


async def test_discover_then_replay_full_pipeline(demo_app_base_url, tmp_path: Path):
    # --- Stage 1: discovery (the only stage allowed to call an LLM) ---
    scripted = ScriptedLLMProvider(
        decisions=[
            _decision(ActionType.CLICK, target=LocatorTargetInput(strategy="role", role="button", name="Sign In")),
            _decision(ActionType.CLICK, target=LocatorTargetInput(strategy="role", role="link", name="Search Members")),
            _decision(ActionType.FILL, target=LocatorTargetInput(strategy="test_id", test_id="member-search-input"), value="12345"),
            _decision(ActionType.CLICK, target=LocatorTargetInput(strategy="test_id", test_id="member-search-submit")),
            # test_id embeds the literal member id, so the recorder can
            # parameterize it to "view-member-${member_id}" - a name-based
            # target (e.g. "View Jordan Alvarez") would overfit to member
            # 12345 and break the reusability check below for member 67890.
            _decision(ActionType.CLICK, target=LocatorTargetInput(strategy="test_id", test_id="view-member-12345")),
            _decision(ActionType.EXTRACT, target=LocatorTargetInput(strategy="test_id", test_id="savings-balance"), output_name="savings_balance"),
            _decision(ActionType.FINISH, finish_summary="Found the balance."),
        ]
    )

    discovery_surface = PlaywrightSurface(headless=True)
    discovery_evidence = EvidenceWriter(evidence_root=tmp_path / "evidence", run_kind="discovery", run_id="e2e")
    discovery_engine = DiscoveryEngine(
        surface=discovery_surface,
        planner=Planner(scripted),
        safety_policy=SafetyPolicy(allowed_domains=("127.0.0.1",)),
        evidence=discovery_evidence,
    )
    try:
        discovery_result = await discovery_engine.run(
            goal="Look up member 12345 and read their current savings balance.",
            start_url=f"{demo_app_base_url}/login",
            capability_id="member_savings_lookup",
            description="Look up a member and return their current savings balance.",
            inputs=[ParameterSpec(name="member_id", type=ParamType.STRING)],
            outputs=[OutputSpec(name="savings_balance", type=ParamType.MONEY)],
            param_values={"member_id": "12345"},
            allowed_domains=("127.0.0.1",),
        )
    finally:
        await discovery_surface.close()

    assert discovery_result.status == DiscoveryStatus.SUCCESS
    assert discovery_result.artifact is not None

    # --- Persist to disk, exactly like the real CLI does ---
    store = ArtifactStore(tmp_path / "capabilities")
    saved_path = store.save(discovery_result.artifact)
    assert saved_path.exists()

    # --- Stage 2: reload from disk and replay - ZERO LLM calls allowed ---
    forbidding_provider = CountingLLMProvider(forbid_calls=True)
    reloaded_artifact = store.load("member_savings_lookup")

    replay_surface = PlaywrightSurface(headless=True)
    replay_evidence = EvidenceWriter(evidence_root=tmp_path / "evidence", run_kind="replay", run_id="e2e")
    replay_engine = ReplayEngine(
        replay_surface,
        safety_policy=SafetyPolicy(allowed_domains=("127.0.0.1",)),
        evidence=replay_evidence,
    )
    try:
        replay_result = await replay_engine.run(reloaded_artifact, {"member_id": "12345"})
    finally:
        await replay_surface.close()

    assert forbidding_provider.call_count == 0
    assert replay_result.status == ReplayStatus.SUCCESS, replay_result.message
    balance = replay_result.outputs["savings_balance"]
    assert isinstance(balance, MoneyValue)
    assert balance.amount == Decimal("4231.55")

    # --- Reusability: replay the SAME artifact with a different member,
    #     never touching the LLM, never editing the artifact file ---
    replay_surface_2 = PlaywrightSurface(headless=True)
    replay_engine_2 = ReplayEngine(
        replay_surface_2, safety_policy=SafetyPolicy(allowed_domains=("127.0.0.1",))
    )
    try:
        second_result = await replay_engine_2.run(reloaded_artifact, {"member_id": "67890"})
    finally:
        await replay_surface_2.close()
    assert second_result.status == ReplayStatus.SUCCESS
    assert second_result.outputs["savings_balance"].amount == Decimal("812.00")
