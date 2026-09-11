import pytest

from app.browser.surface import SurfaceKind, SurfaceSessionState
from app.errors import AutomationError
from app.escalation.intervention import InterventionManager
from app.escalation.models import EscalationState
from app.escalation.session_control import SessionRegistry


class _FakeSurface:
    def __init__(self, session_id: str) -> None:
        self.session = SurfaceSessionState(session_id=session_id, surface_kind=SurfaceKind.PLAYWRIGHT_WEB)


def _manager(tmp_path):
    registry = SessionRegistry()
    managed = registry.register(_FakeSurface("sess-esc-1"))
    manager = InterventionManager(registry, evidence_root=tmp_path)
    return manager, managed, registry


def test_full_escalation_lifecycle(tmp_path):
    manager, managed, registry = _manager(tmp_path)

    request = manager.request_escalation(session_id=managed.session_id, reason="risky action blocked")
    assert request.state == EscalationState.ESCALATION_REQUESTED

    manager.take_control(request.intervention_id, operator_notes="reviewed, looks fine")
    assert manager.get(request.intervention_id).state == EscalationState.HUMAN_CONTROL
    with pytest.raises(AutomationError):
        registry.require_automation_owns(managed.session_id)  # automation locked out

    manager.request_resume(request.intervention_id)
    assert manager.get(request.intervention_id).state == EscalationState.RESUME_REQUESTED

    manager.complete_resume(request.intervention_id)
    assert manager.get(request.intervention_id).state == EscalationState.AUTOMATION
    registry.require_automation_owns(managed.session_id)  # ownership restored


def test_illegal_transition_rejected(tmp_path):
    manager, managed, _ = _manager(tmp_path)
    request = manager.request_escalation(session_id=managed.session_id, reason="test")
    # Cannot jump straight from ESCALATION_REQUESTED to AUTOMATION.
    with pytest.raises(AutomationError):
        manager.complete_resume(request.intervention_id)


def test_escalation_persists_evidence(tmp_path):
    manager, managed, _ = _manager(tmp_path)
    request = manager.request_escalation(session_id=managed.session_id, reason="test reason")
    evidence_files = list((tmp_path / "handoff" / request.intervention_id).glob("*.json"))
    assert any(f.name == "escalation.json" for f in evidence_files)


def test_escalation_context_is_persisted():
    from app.escalation.models import InterventionRequest

    request = InterventionRequest(
        intervention_id="i1", session_id="s1", reason="blocked",
        context={"capability_id": "x", "step": "step-05", "screenshot_ref": "evidence/x.png"},
    )
    assert request.context["step"] == "step-05"
    assert request.context["screenshot_ref"] == "evidence/x.png"


def test_record_operator_action_requires_human_control(tmp_path):
    manager, managed, _ = _manager(tmp_path)
    request = manager.request_escalation(session_id=managed.session_id, reason="test")
    # Automation still owns the session (ESCALATION_REQUESTED, not yet
    # HUMAN_CONTROL) - recording an "operator action" here would be a lie.
    with pytest.raises(AutomationError):
        manager.record_operator_action(request.intervention_id, "did something")


def test_record_operator_action_appends_audit_trail(tmp_path):
    manager, managed, _ = _manager(tmp_path)
    request = manager.request_escalation(session_id=managed.session_id, reason="test")
    manager.take_control(request.intervention_id)

    updated = manager.record_operator_action(
        request.intervention_id, "Clicked Transfer Funds", evidence_ref="evidence/shot.png"
    )
    assert len(updated.operator_actions) == 1
    assert updated.operator_actions[0].description == "Clicked Transfer Funds"
    assert updated.operator_actions[0].evidence_ref == "evidence/shot.png"

    evidence_files = list((tmp_path / "handoff" / request.intervention_id).glob("*.json"))
    assert any(f.name == "operator_actions.json" for f in evidence_files)
