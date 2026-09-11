#!/usr/bin/env python
"""Demonstrate real human escalation/handoff end-to-end and save evidence.

    python scripts/demo_escalation_handoff.py

Drives a scripted agent (no LLM needed for this demo - the safety policy
behavior being demonstrated does not depend on which provider chose the
action) toward the risky "Transfer Funds" action, confirms the safety
policy blocks it and the session survives, then has a simulated operator
take control of the SAME live browser session, complete the action
manually, and hand control back to automation.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.loop import DiscoveryEngine  # noqa: E402
from app.agent.models import ActionType, AgentDecision, LocatorTargetInput  # noqa: E402
from app.agent.planner import Planner  # noqa: E402
from app.browser.locators import LocatorStrategyKind, LocatorTarget  # noqa: E402
from app.browser.playwright_surface import PlaywrightSurface  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.escalation.intervention import InterventionManager  # noqa: E402
from app.escalation.session_control import SessionRegistry  # noqa: E402
from app.observability.evidence import EvidenceWriter  # noqa: E402
from app.providers.mock import ScriptedLLMProvider  # noqa: E402
from app.safety.policy import SafetyPolicy  # noqa: E402
from scripts._common import ensure_demo_app_running  # noqa: E402


def _decision(action: ActionType, **kwargs) -> AgentDecision:
    return AgentDecision(action=action, reasoning="scripted step for handoff demo", **kwargs)


async def main() -> int:
    settings = get_settings()
    demo_proc = ensure_demo_app_running(settings.demo_app_base_url)

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

    surface = PlaywrightSurface(headless=settings.headless_browser)
    evidence = EvidenceWriter(
        evidence_root=settings.evidence_dir, run_kind="handoff", run_id="risky-transfer-demo"
    )
    engine = DiscoveryEngine(
        surface=surface,
        planner=Planner(scripted),
        safety_policy=SafetyPolicy(allowed_domains=(settings.demo_app_host,)),
        evidence=evidence,
        max_steps=10,
    )

    print("[handoff] running agent toward a deliberately risky goal ...")
    result = await engine.run(
        goal="Transfer funds out of member 24680's savings account.",
        start_url=f"{settings.demo_app_base_url}/login",
        capability_id="risky_transfer_demo",
        description="Deliberately risky goal used to demonstrate safety escalation.",
        inputs=[], outputs=[], param_values={},
        allowed_domains=(settings.demo_app_host,),
    )
    print(f"[handoff] discovery status: {result.status.value}")
    print(f"[handoff] message: {result.message}")
    assert result.status.value == "escalated", "expected the safety policy to escalate this run"
    assert surface.session.closed is False, "session must survive escalation for real handoff"

    registry = SessionRegistry()
    managed = registry.register(surface)
    manager = InterventionManager(registry, evidence_root=settings.evidence_dir)

    request = manager.request_escalation(
        session_id=managed.session_id, reason=result.message, run_id=result.run_id,
        context=result.escalation_context,
    )
    print(f"[handoff] escalation created: {request.intervention_id} state={request.state.value}")
    print(f"[handoff] context handed to the operator: {request.context}")

    manager.take_control(request.intervention_id, operator_notes="Reviewed and approved for this demo.")
    print(f"[handoff] operator took control: state={manager.get(request.intervention_id).state.value}")

    print("[handoff] operator completing the risky action manually on the SAME session ...")
    await surface.click(LocatorTarget(strategy=LocatorStrategyKind.ROLE, role="button", name="Transfer Funds"))
    obs = await surface.observe()
    print(f"[handoff] page banners after manual action: {obs.banner_messages}")

    # Record what the human actually did - not just that control changed
    # hands. A fresh screenshot anchors the audit trail to this exact
    # moment.
    action_screenshot = await surface.screenshot(evidence.screenshot_path("operator-transfer-confirmed"))
    manager.record_operator_action(
        request.intervention_id,
        "Operator clicked 'Transfer Funds' to complete the $100.00 transfer "
        "the automation correctly refused to execute itself.",
        evidence_ref=action_screenshot,
    )
    print(f"[handoff] operator action recorded: {manager.get(request.intervention_id).operator_actions}")

    manager.request_resume(request.intervention_id)
    manager.complete_resume(request.intervention_id)
    print(f"[handoff] control returned to automation: state={manager.get(request.intervention_id).state.value}")

    await surface.close()
    if demo_proc:
        demo_proc.terminate()

    print(f"\n[handoff] evidence saved under {settings.evidence_dir}/handoff/")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
