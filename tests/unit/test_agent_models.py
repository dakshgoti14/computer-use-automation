import pytest
from pydantic import ValidationError

from app.agent.models import ActionType, AgentDecision, LocatorTargetInput


def test_click_requires_target():
    with pytest.raises(ValidationError):
        AgentDecision(action=ActionType.CLICK, reasoning="click something")


def test_fill_requires_value():
    target = LocatorTargetInput(strategy="test_id", test_id="member-search-input")
    with pytest.raises(ValidationError):
        AgentDecision(action=ActionType.FILL, reasoning="fill it", target=target)


def test_extract_requires_output_name():
    target = LocatorTargetInput(strategy="test_id", test_id="savings-balance")
    with pytest.raises(ValidationError):
        AgentDecision(action=ActionType.EXTRACT, reasoning="read it", target=target)


def test_finish_requires_summary():
    with pytest.raises(ValidationError):
        AgentDecision(action=ActionType.FINISH, reasoning="done")


def test_valid_extract_decision_converts_to_agent_action():
    target = LocatorTargetInput(strategy="test_id", test_id="savings-balance")
    decision = AgentDecision(
        action=ActionType.EXTRACT, reasoning="read balance", target=target, output_name="savings_balance"
    )
    action = decision.to_agent_action()
    assert action.action == ActionType.EXTRACT
    assert action.target.test_id == "savings-balance"
    assert action.output_name == "savings_balance"


def test_agent_decision_rejects_unknown_action():
    with pytest.raises(ValidationError):
        AgentDecision(action="delete_everything", reasoning="oops")
