"""Proves the discovery path DOES call the LLM provider (contrast with
test_zero_llm_replay.py) and that a full successful discovery run against
the live demo app produces a valid, parameterized, checkpointed capability
artifact - using a scripted provider so this test is fast, free, and
deterministic. The genuine Gemini-driven run is a separate, explicit
command (scripts/discover_capability.py) per the assignment's requirement
that it not be faked in the test suite.
"""

from __future__ import annotations

import pytest

from app.agent.loop import DiscoveryEngine, DiscoveryStatus
from app.agent.models import ActionType, AgentDecision, LocatorTargetInput
from app.agent.planner import Planner
from app.artifacts.schema import OutputSpec, ParameterSpec, ParamType
from app.artifacts.validator import validate_artifact
from app.browser.playwright_surface import PlaywrightSurface
from app.observability.evidence import EvidenceWriter
from app.providers.mock import ScriptedLLMProvider
from app.safety.policy import SafetyPolicy

pytestmark = pytest.mark.asyncio


def _decision(action: ActionType, **kwargs) -> AgentDecision:
    return AgentDecision(action=action, reasoning="scripted step for test", **kwargs)


def _role(role: str, name: str) -> LocatorTargetInput:
    return LocatorTargetInput(strategy="role", role=role, name=name)


def _test_id(test_id: str) -> LocatorTargetInput:
    return LocatorTargetInput(strategy="test_id", test_id=test_id)


async def test_discovery_calls_llm_and_produces_valid_artifact(demo_app_base_url, tmp_path):
    scripted = ScriptedLLMProvider(
        decisions=[
            _decision(ActionType.CLICK, target=_role("button", "Sign In")),
            _decision(ActionType.CLICK, target=_role("link", "Search Members")),
            _decision(ActionType.FILL, target=_test_id("member-search-input"), value="12345"),
            _decision(ActionType.CLICK, target=_test_id("member-search-submit")),
            # Deliberately targets by test_id (which embeds the literal
            # member id) rather than by the member's display name, so the
            # recorder's parameterization turns this into a reusable
            # "view-member-${member_id}" target - see
            # tests/e2e/test_full_lifecycle.py for why that distinction
            # matters (a name-based target would silently overfit to this
            # one member and break replay for any other member_id).
            _decision(ActionType.CLICK, target=_test_id("view-member-12345")),
            _decision(
                ActionType.EXTRACT, target=_test_id("savings-balance"), output_name="savings_balance"
            ),
            _decision(ActionType.FINISH, finish_summary="Found the savings balance for member 12345."),
        ]
    )

    surface = PlaywrightSurface(headless=True)
    evidence = EvidenceWriter(evidence_root=tmp_path, run_kind="discovery", run_id="test-run")
    engine = DiscoveryEngine(
        surface=surface,
        planner=Planner(scripted),
        safety_policy=SafetyPolicy(allowed_domains=("127.0.0.1",)),
        evidence=evidence,
        max_steps=10,
    )

    try:
        result = await engine.run(
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
        await surface.close()

    # The LLM provider WAS actually called, once per step - the opposite of
    # the zero-call guarantee that ReplayEngine must uphold.
    assert scripted.call_count == 7

    assert result.status == DiscoveryStatus.SUCCESS, result.message
    assert result.artifact is not None
    validate_artifact(result.artifact)  # the produced artifact is well-formed

    # Independence from the transcript: nothing in the artifact is a stored
    # LLM message/prompt, and the literal "12345" was templated away.
    artifact_json = result.artifact.model_dump_json()
    assert "12345" not in artifact_json
    assert "${member_id}" in artifact_json
    assert result.artifact.outputs[0].name == "savings_balance"

    events = evidence.read_events()
    assert any(e["event_type"] == "agent_decision" for e in events)
    assert any(e["event_type"] == "artifact_created" for e in events)
