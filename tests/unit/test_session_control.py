import pytest

from app.browser.surface import SessionOwner, SurfaceKind, SurfaceSessionState
from app.errors import AutomationError
from app.escalation.session_control import SessionRegistry


class _FakeSurface:
    """Minimal stand-in for SurfaceAdapter - session control only needs
    ``.session``, not real browser behaviour."""

    def __init__(self) -> None:
        self.session = SurfaceSessionState(session_id="sess-1", surface_kind=SurfaceKind.PLAYWRIGHT_WEB)


def test_new_session_defaults_to_automation_owner():
    registry = SessionRegistry()
    managed = registry.register(_FakeSurface())
    assert managed.owner == SessionOwner.AUTOMATION
    registry.require_automation_owns(managed.session_id)  # must not raise


def test_transfer_to_human_blocks_automation():
    registry = SessionRegistry()
    managed = registry.register(_FakeSurface())
    registry.transfer_to_human(managed.session_id)
    with pytest.raises(AutomationError):
        registry.require_automation_owns(managed.session_id)


def test_cannot_double_transfer_to_human():
    registry = SessionRegistry()
    managed = registry.register(_FakeSurface())
    registry.transfer_to_human(managed.session_id)
    with pytest.raises(AutomationError):
        registry.transfer_to_human(managed.session_id)


def test_resume_automation_restores_ownership():
    registry = SessionRegistry()
    managed = registry.register(_FakeSurface())
    registry.transfer_to_human(managed.session_id)
    registry.resume_automation(managed.session_id)
    registry.require_automation_owns(managed.session_id)  # must not raise


def test_unknown_session_raises_typed_error():
    registry = SessionRegistry()
    with pytest.raises(AutomationError):
        registry.get("does-not-exist")
