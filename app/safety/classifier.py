"""Heuristic risk classification for a candidate action.

Deliberately simple and explainable (keyword + action-type based) rather
than another LLM call - safety decisions must be deterministic and
auditable, not themselves subject to model variance.
"""

from __future__ import annotations

from enum import Enum

from app.agent.models import ActionType, AgentAction

#: Substrings (case-insensitive) that mark an action's target as high-risk:
#: irreversible, money-moving, or account-altering. Matched against the
#: target's accessible name / label / text / test_id / value.
RESTRICTED_KEYWORDS: tuple[str, ...] = (
    "transfer",
    "delete",
    "remove",
    "approve",
    "close account",
    "withdraw",
    "wire",
    "change password",
    "update contact",
    "reset pin",
    "grant access",
    "override",
)


class RiskLevel(str, Enum):
    SAFE = "safe"
    RESTRICTED = "restricted"  # requires confirmation / must be blocked automatically
    BLOCKED = "blocked"  # never allowed regardless of confirmation


def _target_text(action: AgentAction) -> str:
    if action.target is None:
        return ""
    parts = [action.target.name, action.target.label, action.target.text, action.target.test_id]
    return " ".join(p for p in parts if p).lower()


def classify_risk(action: AgentAction) -> RiskLevel:
    """Classify how risky an action is, independent of domain allowlisting."""

    if action.action == ActionType.NAVIGATE:
        # Domain allowlisting is handled by SafetyPolicy; navigation itself
        # is only "restricted" (needs an allowlist check), not inherently
        # blocked.
        return RiskLevel.RESTRICTED

    haystack = _target_text(action) + " " + (action.value or "")
    haystack = haystack.lower()
    for keyword in RESTRICTED_KEYWORDS:
        if keyword in haystack:
            return RiskLevel.BLOCKED

    if action.action in (ActionType.CLICK, ActionType.FILL, ActionType.SELECT):
        return RiskLevel.SAFE
    if action.action in (ActionType.EXTRACT, ActionType.WAIT, ActionType.FINISH,
                          ActionType.ESCALATE):
        return RiskLevel.SAFE
    return RiskLevel.RESTRICTED
