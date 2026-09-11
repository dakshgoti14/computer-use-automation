"""Independent safety policy layer.

Every action - whether proposed by the live LLM during discovery or replayed
from an artifact - passes through :meth:`SafetyPolicy.evaluate` before it
reaches a surface adapter. The LLM cannot bypass this: the agent loop and
replay engine both call it unconditionally, and it is pure/deterministic
(no LLM call of its own).
"""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel

from app.agent.models import ActionType, AgentAction
from app.safety.classifier import RiskLevel, classify_risk


class PolicyDecision(BaseModel):
    allowed: bool
    risk_level: RiskLevel
    requires_confirmation: bool = False
    escalate: bool = False
    reason: str


class SafetyPolicy:
    """Configurable allow/deny policy for domains, routes, and action types."""

    def __init__(
        self,
        *,
        allowed_domains: tuple[str, ...],
        allowed_action_types: tuple[ActionType, ...] = (
            ActionType.CLICK,
            ActionType.FILL,
            ActionType.SELECT,
            ActionType.EXTRACT,
            ActionType.WAIT,
            ActionType.FINISH,
            ActionType.ESCALATE,
        ),
        navigation_allowed: bool = True,
    ) -> None:
        self.allowed_domains = allowed_domains
        self.allowed_action_types = set(allowed_action_types) | {
            ActionType.NAVIGATE
        }  # navigate is domain-checked below, not blanket-disallowed
        self.navigation_allowed = navigation_allowed

    def _domain_allowed(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return any(host == d or host.endswith(f".{d}") for d in self.allowed_domains)

    def evaluate(self, action: AgentAction, *, current_url: str) -> PolicyDecision:
        risk = classify_risk(action)

        if action.action == ActionType.NAVIGATE:
            if not self.navigation_allowed:
                return PolicyDecision(
                    allowed=False,
                    risk_level=risk,
                    escalate=True,
                    reason="Navigation is disabled by policy for this capability.",
                )
            if not action.url or not self._domain_allowed(action.url):
                return PolicyDecision(
                    allowed=False,
                    risk_level=risk,
                    escalate=True,
                    reason=(
                        f"Navigation target {action.url!r} is outside the allowed "
                        f"domain list {self.allowed_domains}."
                    ),
                )
            return PolicyDecision(allowed=True, risk_level=risk, reason="Navigation in-domain.")

        if risk == RiskLevel.BLOCKED:
            return PolicyDecision(
                allowed=False,
                risk_level=risk,
                escalate=True,
                reason=(
                    "Action target matched a restricted-keyword pattern "
                    "(money movement / irreversible account change). Automation "
                    "must not execute this without explicit human approval."
                ),
            )

        if not self._domain_allowed(current_url):
            return PolicyDecision(
                allowed=False,
                risk_level=risk,
                escalate=True,
                reason=f"Current page {current_url!r} is outside the allowed domain list.",
            )

        if action.action not in self.allowed_action_types:
            return PolicyDecision(
                allowed=False,
                risk_level=risk,
                escalate=True,
                reason=f"Action type {action.action} is not in the allowlist for this run.",
            )

        return PolicyDecision(allowed=True, risk_level=risk, reason="Action within policy.")
