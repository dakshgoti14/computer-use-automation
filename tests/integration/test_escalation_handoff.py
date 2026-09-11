"""Real human-handoff proof: a risky action gets escalated (not silently
executed), the SAME live browser session survives the escalation, a
simulated operator takes control and completes the risky action manually,
and control is then handed back to automation - all on one session, never
closing the browser in between.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.loop import DiscoveryEngine, DiscoveryStatus
from app.agent.models import ActionType, AgentDecision, LocatorTargetInput
from app.agent.planner import Planner
from app.browser.locators import LocatorStrategyKind, LocatorTarget
from app.browser.playwright_surface import PlaywrightSurface
from app.escalation.intervention import InterventionManager
from app.escalation.models import EscalationState
from app.escalation.session_control import SessionRegistry
from app.observability.evidence import EvidenceWriter
from app.providers.mock import ScriptedLLMProvider
from app.safety.policy import SafetyPolicy

pytestmark = pytest.mark.asyncio


def _decision(action: ActionType, **kwargs) -> AgentDecision:
    return AgentDecision(action=action, reasoning="scripted step for test", **kwargs)


async def test_risky_action_escalates_and_session_survives_for_human_handoff(
    demo_app_base_url, tmp_path
):
    # The agent is (mis)directed toward the risky "Transfer Funds" action.
    # The safety policy must block it before it ever reaches the browser.
    # Uses member 24680, a member not asserted on by any balance-checking
    # test elsewhere in the suite - the human-operator step below performs a
    # REAL transfer against the shared demo app process, and other tests
    # must not observe that mutation.
    scripted = ScriptedLLMProvider(
        decisions=[
            _decision(ActionType.CLICK, target=LocatorTargetInput(strategy="role", role="button", name="Sign In")),
            _decision(ActionType.CLICK, target=LocatorTargetInput(strategy="role", role="link", name="Search Members")),
            _decision(ActionType.FILL, target=LocatorTargetInput(strategy="test_id", test_id="member-search-input"), value="24680"),
            _decision(ActionType.CLICK, target=LocatorTargetInput(strategy="test_id", test_id="member-search-submit")),
            _decision(ActionType.CLICK, target=LocatorTargetInput(strategy="role", role="link", name="View Sam Whitfield")),
            _decision(ActionType.CLICK, target=LocatorTargetInput(strategy="role", role="link", name="Account Actions")),
            _decision(ActionType.CLICK, target=LocatorTargetInput(strategy="role", role="button", name="Transfer Funds")),
        ]
    )

    surface = PlaywrightSurface(headless=True)
    evidence = EvidenceWriter(evidence_root=tmp_path, run_kind="handoff", run_id="risky-action-test")
    engine = DiscoveryEngine(
        surface=surface,
        planner=Planner(scripted),
        safety_policy=SafetyPolicy(allowed_domains=("127.0.0.1",)),
        evidence=evidence,
        max_steps=10,
    )

    result = await engine.run(
        goal="Transfer funds out of member 24680's savings account.",
        start_url=f"{demo_app_base_url}/login",
        capability_id="risky_transfer_demo",
        description="Deliberately risky goal used to prove safety escalation.",
        inputs=[],
        outputs=[],
        param_values={},
        allowed_domains=("127.0.0.1",),
    )

    # Escalated, not executed: the transfer must never have happened.
    assert result.status == DiscoveryStatus.ESCALATED
    assert "policy" in result.message.lower() or "blocked" in result.message.lower()

    # The escalation carries actionable context, not just a reason string -
    # which capability/goal, the step, the page, and a fresh screenshot.
    assert result.escalation_context["capability_id"] == "risky_transfer_demo"
    assert result.escalation_context["step"]
    assert Path(result.escalation_context["screenshot_ref"]).exists()

    # The session is NOT closed - this is what makes it a real handoff
    # rather than a termination. Prove it by continuing to use the same
    # surface/page after DiscoveryEngine returned.
    assert surface.session.closed is False
    current_url = await surface.current_url()
    assert "/actions" in current_url  # still parked exactly where it stopped

    # Wire up the escalation state machine on this same session.
    registry = SessionRegistry()
    managed = registry.register(surface)
    manager = InterventionManager(registry, evidence_root=tmp_path)

    request = manager.request_escalation(
        session_id=managed.session_id, reason=result.message, run_id=result.run_id,
        context=result.escalation_context,
    )
    manager.take_control(request.intervention_id, operator_notes="Approved by ops for this test.")
    assert manager.get(request.intervention_id).state == EscalationState.HUMAN_CONTROL

    # A human operator now drives the SAME live page directly (bypassing the
    # agent loop entirely, as a real operator would in a browser window) to
    # complete the action the automation correctly refused to do itself.
    await surface.click(LocatorTarget(strategy=LocatorStrategyKind.ROLE, role="button", name="Transfer Funds"))
    obs = await surface.observe()
    assert any("transferred" in b.lower() for b in obs.banner_messages)

    # What the human did is recorded, not just that control changed hands.
    manager.record_operator_action(request.intervention_id, "Clicked Transfer Funds to complete the transfer.")
    assert len(manager.get(request.intervention_id).operator_actions) == 1

    # Control now hands back to automation on the SAME session.
    manager.request_resume(request.intervention_id)
    manager.complete_resume(request.intervention_id)
    assert manager.get(request.intervention_id).state == EscalationState.AUTOMATION
    registry.require_automation_owns(managed.session_id)  # must not raise

    handoff_dir = Path(tmp_path) / "handoff" / request.intervention_id
    assert (handoff_dir / "escalation.json").exists()
    assert (handoff_dir / "handoff.json").exists()
    assert (handoff_dir / "resumed.json").exists()

    await surface.close()
