"""The discovery agent loop: OBSERVE -> DECIDE -> VALIDATE -> ACT -> OBSERVE.

This is ``DiscoveryEngine`` from the architecture rule in REPORT.md:

    DiscoveryEngine -> LLMProvider -> CapabilityArtifact

It is the *only* place in the system where an LLM call and a live browser
action happen in the same control flow. Once a capability artifact exists,
:mod:`app.replay.executor` takes over and never comes back here.

Ownership of the browser session on escalation: this loop never closes the
surface itself. The caller (script or API route) decides whether to close
it (success / hard failure) or keep it alive for human handoff (escalated) -
see app/escalation/session_control.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from app.agent.models import ActionType, AgentAction
from app.agent.planner import Planner
from app.artifacts.recorder import DiscoveryRecorder
from app.artifacts.schema import CapabilityArtifact, OutputSpec, ParameterSpec
from app.browser.surface import SurfaceAdapter
from app.errors import AutomationError, ErrorCode
from app.observability.events import Event, EventType
from app.observability.evidence import EvidenceWriter
from app.safety.policy import SafetyPolicy


class DiscoveryStatus(str, Enum):
    SUCCESS = "success"
    ESCALATED = "escalated"
    HARD_FAILURE = "hard_failure"


@dataclass
class DiscoveryResult:
    status: DiscoveryStatus
    message: str
    run_id: str
    steps_taken: int
    artifact: CapabilityArtifact | None = None
    escalation_reason: str | None = None
    evidence_ref: str | None = None
    #: Populated only when status == ESCALATED. Carries exactly what an
    #: intervention request needs to be actionable rather than a bare
    #: reason string: which capability/goal was running, the step it
    #: stopped on, the page it was looking at, and a screenshot taken at
    #: the moment of escalation - see app/escalation/models.py.
    escalation_context: dict[str, str] = field(default_factory=dict)


class DiscoveryEngine:
    def __init__(
        self,
        *,
        surface: SurfaceAdapter,
        planner: Planner,
        safety_policy: SafetyPolicy,
        evidence: EvidenceWriter,
        max_steps: int = 20,
    ) -> None:
        self.surface = surface
        self.planner = planner
        self.safety_policy = safety_policy
        self.evidence = evidence
        self.max_steps = max_steps

    async def run(
        self,
        *,
        goal: str,
        start_url: str,
        capability_id: str,
        description: str,
        inputs: list[ParameterSpec],
        outputs: list[OutputSpec],
        param_values: dict[str, str],
        allowed_domains: tuple[str, ...],
    ) -> DiscoveryResult:
        run_id = str(uuid.uuid4())
        history: list[str] = []
        recorder = DiscoveryRecorder(
            capability_id=capability_id,
            description=description,
            inputs=inputs,
            outputs=outputs,
            param_values=param_values,
            allowed_domains=allowed_domains,
            start_url=start_url,
            discovery_run_id=run_id,
        )

        await self.surface.start_session(start_url)
        self._log(run_id, EventType.RUN_STARTED, details={
            "goal": goal, "capability_id": capability_id,
        })

        for step_number in range(1, self.max_steps + 1):
            observation = await self.surface.observe()
            url_before = observation.url
            self.evidence.save_observation(f"step-{step_number:02d}-before", observation.model_dump())
            await self.surface.screenshot(
                self.evidence.screenshot_path(f"step-{step_number:02d}-before")
            )
            self._log(run_id, EventType.OBSERVATION, step_id=f"step-{step_number:02d}",
                       details={"url": observation.url, "title": observation.title})

            try:
                action = await self.planner.decide(
                    goal=goal,
                    observation_text=observation.to_prompt_text(),
                    history_text="\n".join(history),
                    step_number=step_number,
                    max_steps=self.max_steps,
                )
            except AutomationError as exc:
                self._log(run_id, EventType.ERROR, step_id=f"step-{step_number:02d}",
                           error_code=exc.code.value,
                           details={"message": exc.message, "context": exc.context})
                return DiscoveryResult(
                    status=DiscoveryStatus.HARD_FAILURE, message=exc.message,
                    run_id=run_id, steps_taken=step_number,
                )

            self._log(run_id, EventType.AGENT_DECISION, step_id=f"step-{step_number:02d}",
                       action=action.action.value,
                       target=action.target.describe() if action.target else None,
                       details={"reasoning": action.reasoning})

            if action.action == ActionType.FINISH:
                if not recorder._steps:  # noqa: SLF001 - internal check, same module family
                    return DiscoveryResult(
                        status=DiscoveryStatus.HARD_FAILURE,
                        message="Agent declared finish without taking any recordable action.",
                        run_id=run_id, steps_taken=step_number,
                    )
                artifact = recorder.finalize()
                self._log(run_id, EventType.ARTIFACT_CREATED, details={
                    "capability_id": artifact.capability_id, "steps": len(artifact.steps),
                })
                return DiscoveryResult(
                    status=DiscoveryStatus.SUCCESS, message=action.finish_summary or "done",
                    run_id=run_id, steps_taken=step_number, artifact=artifact,
                    evidence_ref=str(self.evidence.run_dir),
                )

            if action.action == ActionType.ESCALATE:
                self._log(run_id, EventType.ESCALATION_REQUESTED, step_id=f"step-{step_number:02d}",
                           details={"reason": action.escalation_reason})
                context = await self._build_escalation_context(
                    capability_id=capability_id, goal=goal, step_number=step_number,
                )
                return DiscoveryResult(
                    status=DiscoveryStatus.ESCALATED,
                    message=action.escalation_reason or "Agent requested escalation.",
                    run_id=run_id, steps_taken=step_number,
                    escalation_reason=action.escalation_reason,
                    evidence_ref=str(self.evidence.run_dir),
                    escalation_context=context,
                )

            policy_decision = self.safety_policy.evaluate(action, current_url=url_before)
            self._log(run_id, EventType.POLICY_DECISION, step_id=f"step-{step_number:02d}",
                       status="allowed" if policy_decision.allowed else "blocked",
                       details={"reason": policy_decision.reason, "risk": policy_decision.risk_level.value})

            if not policy_decision.allowed:
                context = await self._build_escalation_context(
                    capability_id=capability_id, goal=goal, step_number=step_number,
                    attempted_action=f"{action.action.value} "
                    f"{action.target.describe() if action.target else ''}".strip(),
                )
                return DiscoveryResult(
                    status=DiscoveryStatus.ESCALATED,
                    message=f"Safety policy blocked action: {policy_decision.reason}",
                    run_id=run_id, steps_taken=step_number,
                    escalation_reason=policy_decision.reason,
                    evidence_ref=str(self.evidence.run_dir),
                    escalation_context=context,
                )

            extracted, error = await self._execute(action)
            url_after = await self.surface.current_url()

            if error is not None:
                self._log(run_id, EventType.ERROR, step_id=f"step-{step_number:02d}",
                           error_code=error.code.value,
                           details={"message": error.message, "context": error.context})
                history.append(
                    f"Step {step_number}: {action.action.value} "
                    f"{action.target.describe() if action.target else ''} -> "
                    f"ERROR ({error.code.value}): {error.message}"
                )
                continue  # let the agent see the error via the next observation and adapt

            recorder.record(
                action=action,
                description=action.reasoning,
                url_before=url_before,
                url_after=url_after,
                extracted_value=extracted,
            )
            history.append(
                f"Step {step_number}: {action.action.value} "
                f"{action.target.describe() if action.target else ''} -> success"
                + (f" (extracted: {extracted!r})" if extracted else "")
            )
            self._log(run_id, EventType.ACTION_EXECUTED, step_id=f"step-{step_number:02d}",
                       action=action.action.value, status="success")

        return DiscoveryResult(
            status=DiscoveryStatus.HARD_FAILURE,
            message=f"Exceeded max_steps={self.max_steps} without reaching finish/escalate.",
            run_id=run_id, steps_taken=self.max_steps,
        )

    async def _execute(self, action: AgentAction) -> tuple[str | None, AutomationError | None]:
        # AgentAction's own validator already guarantees `target` is set for
        # every action type handled below (see app.agent.models); asserting
        # it here narrows the type for the type checker without weakening
        # SurfaceAdapter's contract to accept `None`.
        try:
            if action.action == ActionType.CLICK:
                assert action.target is not None
                await self.surface.click(action.target)
                return None, None
            if action.action == ActionType.FILL:
                assert action.target is not None
                await self.surface.fill(action.target, action.value or "")
                return None, None
            if action.action == ActionType.SELECT:
                assert action.target is not None
                await self.surface.select(action.target, action.value or "")
                return None, None
            if action.action == ActionType.EXTRACT:
                assert action.target is not None
                value = await self.surface.extract(action.target)
                return value, None
            if action.action == ActionType.WAIT:
                assert action.target is not None
                ok = await self.surface.wait_for(action.target, timeout_ms=5000)
                if not ok:
                    from app.errors import RecoverableError

                    return None, RecoverableError(
                        ErrorCode.TRANSIENT_LOAD_STATE, "Timed out waiting for element"
                    )
                return None, None
            if action.action == ActionType.NAVIGATE:
                await self.surface.navigate(action.url or "")
                return None, None
        except AutomationError as exc:
            return None, exc
        return None, None

    async def _build_escalation_context(
        self,
        *,
        capability_id: str,
        goal: str,
        step_number: int,
        attempted_action: str | None = None,
    ) -> dict[str, str]:
        """Everything an operator needs to act on an intervention request
        without re-deriving it: which capability/goal, the step it stopped
        on, the current page, and a screenshot taken at this exact moment -
        not just the reason string.
        """

        step_id = f"step-{step_number:02d}"
        screenshot_ref = await self.surface.screenshot(
            self.evidence.screenshot_path(f"{step_id}-escalation")
        )
        context = {
            "capability_id": capability_id,
            "goal": goal,
            "step": step_id,
            "current_url": await self.surface.current_url(),
            "screenshot_ref": screenshot_ref,
        }
        if attempted_action:
            context["attempted_action"] = attempted_action
        return context

    def _log(self, run_id: str, event_type: EventType, **fields: object) -> None:
        self.evidence.record_event(
            Event(run_id=run_id, session_id=self.surface.session.session_id,
                  event_type=event_type, **fields)  # type: ignore[arg-type]
        )
