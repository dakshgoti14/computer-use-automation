"""Intervention lifecycle: create an escalation, transfer control, resume automation.

Coordinates :class:`app.escalation.session_control.SessionRegistry` (who owns
the browser) with :class:`app.escalation.models.InterventionRequest` (why we
escalated, and the state-machine position), and persists intervention
records to evidence so a handoff leaves an audit trail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.errors import ErrorCode, HardFailureError
from app.escalation.models import (
    ALLOWED_TRANSITIONS,
    EscalationState,
    InterventionRequest,
    OperatorAction,
)
from app.escalation.session_control import SessionRegistry
from app.observability.evidence import EvidenceWriter


class InterventionManager:
    def __init__(self, sessions: SessionRegistry, *, evidence_root: Path) -> None:
        self._sessions = sessions
        self._evidence_root = evidence_root
        self._interventions: dict[str, InterventionRequest] = {}

    def _transition(self, request: InterventionRequest, target: EscalationState) -> None:
        allowed = ALLOWED_TRANSITIONS.get(request.state, set())
        if target not in allowed:
            raise HardFailureError(
                ErrorCode.UNSUPPORTED_ACTION,
                f"Illegal escalation transition {request.state} -> {target}",
            )
        request.state = target
        request.updated_at = datetime.now(UTC).isoformat()

    def request_escalation(
        self, *, session_id: str, reason: str, run_id: str | None = None, context: dict[str, str] | None = None
    ) -> InterventionRequest:
        intervention_id = str(uuid.uuid4())
        request = InterventionRequest(
            intervention_id=intervention_id, session_id=session_id, run_id=run_id,
            reason=reason, state=EscalationState.ESCALATION_REQUESTED, context=context or {},
        )
        self._interventions[intervention_id] = request
        self._persist(request, "escalation.json")
        return request

    def take_control(self, intervention_id: str, *, operator_notes: str | None = None) -> InterventionRequest:
        request = self.get(intervention_id)
        self._transition(request, EscalationState.HUMAN_CONTROL)
        self._sessions.transfer_to_human(request.session_id)
        if operator_notes:
            request.operator_notes = operator_notes
        self._persist(request, "handoff.json")
        return request

    def record_operator_action(
        self, intervention_id: str, description: str, *, evidence_ref: str | None = None
    ) -> InterventionRequest:
        """Append one entry to the audit trail of what the human did.

        Only valid while the operator actually holds control - recording an
        "operator action" against a session automation still owns would be
        a lie about who did what.
        """

        request = self.get(intervention_id)
        if request.state != EscalationState.HUMAN_CONTROL:
            raise HardFailureError(
                ErrorCode.UNSUPPORTED_ACTION,
                f"Cannot record an operator action while intervention "
                f"{intervention_id} is in state {request.state}, not HUMAN_CONTROL.",
            )
        request.operator_actions.append(
            OperatorAction(description=description, evidence_ref=evidence_ref)
        )
        request.updated_at = datetime.now(UTC).isoformat()
        self._persist(request, "operator_actions.json")
        return request

    def request_resume(self, intervention_id: str) -> InterventionRequest:
        request = self.get(intervention_id)
        self._transition(request, EscalationState.RESUME_REQUESTED)
        self._persist(request, "resume_requested.json")
        return request

    def complete_resume(self, intervention_id: str) -> InterventionRequest:
        request = self.get(intervention_id)
        self._transition(request, EscalationState.AUTOMATION)
        self._sessions.resume_automation(request.session_id)
        self._persist(request, "resumed.json")
        return request

    def get(self, intervention_id: str) -> InterventionRequest:
        if intervention_id not in self._interventions:
            raise HardFailureError(
                ErrorCode.UNSUPPORTED_ACTION, f"No intervention with id {intervention_id!r}"
            )
        return self._interventions[intervention_id]

    def list_interventions(self) -> list[InterventionRequest]:
        return list(self._interventions.values())

    def _persist(self, request: InterventionRequest, filename: str) -> None:
        writer = EvidenceWriter(
            evidence_root=self._evidence_root, run_kind="handoff", run_id=request.intervention_id
        )
        writer.save_json(filename, request.model_dump())
