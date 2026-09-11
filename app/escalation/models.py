"""Escalation state machine and data models.

    AUTOMATION -> ESCALATION_REQUESTED -> HUMAN_CONTROL -> RESUME_REQUESTED -> AUTOMATION

The browser session survives every transition - escalation pauses
automation and preserves the live session for a human operator; it never
terminates the browser and calls that "handoff".
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class EscalationState(str, Enum):
    AUTOMATION = "automation"
    ESCALATION_REQUESTED = "escalation_requested"
    HUMAN_CONTROL = "human_control"
    RESUME_REQUESTED = "resume_requested"


#: Explicit transition table - anything not listed here is rejected by
#: InterventionManager, preventing invalid jumps (e.g. straight from
#: AUTOMATION to HUMAN_CONTROL without a recorded escalation request).
ALLOWED_TRANSITIONS: dict[EscalationState, set[EscalationState]] = {
    EscalationState.AUTOMATION: {EscalationState.ESCALATION_REQUESTED},
    EscalationState.ESCALATION_REQUESTED: {EscalationState.HUMAN_CONTROL},
    EscalationState.HUMAN_CONTROL: {EscalationState.RESUME_REQUESTED},
    EscalationState.RESUME_REQUESTED: {EscalationState.AUTOMATION},
}


class OperatorAction(BaseModel):
    """One thing a human operator did while holding control of a session.

    Recorded so a handoff leaves an audit trail of what the human actually
    did, not just that control changed hands - the assignment is explicit
    that this must be captured, not merely implied by the state transition.
    """

    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    description: str
    evidence_ref: str | None = None


class InterventionRequest(BaseModel):
    intervention_id: str
    session_id: str
    run_id: str | None = None
    reason: str
    state: EscalationState = EscalationState.ESCALATION_REQUESTED
    context: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    operator_notes: str | None = None
    operator_actions: list[OperatorAction] = Field(default_factory=list)
