from app.agent.models import ActionType, AgentAction
from app.browser.locators import LocatorStrategyKind, LocatorTarget
from app.safety.classifier import RiskLevel, classify_risk
from app.safety.policy import SafetyPolicy


def _click(name: str) -> AgentAction:
    return AgentAction(
        action=ActionType.CLICK, reasoning="test",
        target=LocatorTarget(strategy=LocatorStrategyKind.ROLE, role="button", name=name),
    )


def test_transfer_funds_classified_as_blocked():
    assert classify_risk(_click("Transfer Funds")) == RiskLevel.BLOCKED


def test_ordinary_click_classified_as_safe():
    assert classify_risk(_click("Search")) == RiskLevel.SAFE


def test_policy_blocks_transfer_funds_and_requests_escalation():
    policy = SafetyPolicy(allowed_domains=("example.test",))
    decision = policy.evaluate(_click("Transfer Funds"), current_url="http://example.test/members/1/actions")
    assert decision.allowed is False
    assert decision.escalate is True


def test_policy_allows_ordinary_click_in_domain():
    policy = SafetyPolicy(allowed_domains=("example.test",))
    decision = policy.evaluate(_click("Search"), current_url="http://example.test/members/search")
    assert decision.allowed is True


def test_policy_blocks_action_outside_current_domain():
    policy = SafetyPolicy(allowed_domains=("example.test",))
    decision = policy.evaluate(_click("Search"), current_url="http://evil.test/phish")
    assert decision.allowed is False
    assert decision.escalate is True


def test_policy_blocks_navigate_outside_domain():
    action = AgentAction(action=ActionType.NAVIGATE, reasoning="go", url="http://evil.test/x")
    policy = SafetyPolicy(allowed_domains=("example.test",))
    decision = policy.evaluate(action, current_url="http://example.test/dashboard")
    assert decision.allowed is False


def test_policy_allows_navigate_within_domain():
    action = AgentAction(action=ActionType.NAVIGATE, reasoning="go", url="http://example.test/members/search")
    policy = SafetyPolicy(allowed_domains=("example.test",))
    decision = policy.evaluate(action, current_url="http://example.test/dashboard")
    assert decision.allowed is True


def test_delete_keyword_blocked_via_value_field():
    action = AgentAction(
        action=ActionType.FILL, reasoning="test",
        target=LocatorTarget(strategy=LocatorStrategyKind.TEST_ID, test_id="cmd"),
        value="delete account",
    )
    policy = SafetyPolicy(allowed_domains=("example.test",))
    decision = policy.evaluate(action, current_url="http://example.test/dashboard")
    assert decision.allowed is False
