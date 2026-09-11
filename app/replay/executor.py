"""Deterministic replay engine.

STRUCTURAL GUARANTEE: this module imports nothing from ``app.providers`` or
``app.agent`` (only the pure ``app.agent.models`` action-type enum, which
carries no LLM dependency). There is no code path from here that can reach
an LLM call. ``tests/unit/test_zero_llm_replay.py`` proves this at runtime
too, by wiring a call-forbidding provider stand-in through the surrounding
wiring and asserting it is never touched.

    ReplayEngine -> CapabilityArtifact -> SurfaceAdapter -> deterministic result

Contrast with discovery (app/agent/loop.py):

    DiscoveryEngine -> LLMProvider -> CapabilityArtifact
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from app.agent.models import ActionType, AgentAction
from app.artifacts.schema import (
    CapabilityArtifact,
    CapabilityStep,
    ErrorMappingRule,
    ParamType,
    resolve_template,
)
from app.artifacts.validator import validate_artifact
from app.browser.locators import LocatorTarget
from app.browser.observation import Observation
from app.browser.surface import SurfaceAdapter
from app.errors import (
    AutomationError,
    BusinessOutcomeError,
    ErrorCategory,
    ErrorCode,
    HardFailureError,
    RecoverableError,
)
from app.observability.events import Event, EventType
from app.observability.evidence import EvidenceWriter
from app.replay.checkpoints import CheckpointResult, evaluate_checkpoint
from app.replay.errors import RetryPolicy
from app.replay.result import ReplayResult, ReplayStatus, StepOutcome, parse_typed_output
from app.safety.policy import SafetyPolicy

#: Error codes that trigger a bounded, generic recovery attempt: re-navigate
#: to the capability's start URL and re-run the capability FROM STEP ONE
#: (not just the failed step - a session timeout invalidates everything
#: after re-authentication, e.g. "logged in" and "on the search page" are no
#: longer true). Deliberately small and explicit - replay never improvises a
#: recovery strategy.
_RECOVERABLE_VIA_FULL_RESTART = frozenset({ErrorCode.SESSION_TIMEOUT})


class _RestartCapability(Exception):
    """Internal control-flow signal: unwind to ``run()`` and restart from
    step one after a full-restart recovery action. Never escapes this module."""

    def __init__(self, error: AutomationError) -> None:
        super().__init__(error.message)
        self.error = error


@dataclass
class ResolvedStep:
    step: CapabilityStep
    target: LocatorTarget | None
    value: str | None
    url: str | None


def _resolve_locator_params(target: LocatorTarget | None, params: dict[str, str]) -> LocatorTarget | None:
    """Substitute ``${param}`` references inside a locator's own text fields.

    This is what lets a single step target a row selected by an input
    parameter (e.g. ``test_id="view-member-${member_id}"``) instead of every
    capability being restricted to clicking a fixed, hard-coded element.
    """

    if target is None:
        return None

    def _sub(value: str | None) -> str | None:
        return resolve_template(value, params) if value else value

    return target.model_copy(
        update={
            "test_id": _sub(target.test_id),
            "text": _sub(target.text),
            "name": _sub(target.name),
            "label": _sub(target.label),
            "css": _sub(target.css),
            "fallbacks": [_resolve_locator_params(fb, params) for fb in target.fallbacks],
        }
    )


def _resolve_step(
    step: CapabilityStep, params: dict[str, str], artifact: CapabilityArtifact, profile_id: str | None
) -> ResolvedStep:
    target = step.target
    if profile_id:
        profile = artifact.locator_profile(profile_id)
        if profile and step.step_id in profile.step_target_overrides:
            target = profile.step_target_overrides[step.step_id]

    try:
        target = _resolve_locator_params(target, params)
        value = resolve_template(step.value_template, params) if step.value_template else None
        url = resolve_template(step.url_template, params) if step.url_template else None
    except KeyError as exc:
        raise HardFailureError(
            ErrorCode.PARAMETER_RESOLUTION_FAILED,
            f"Step {step.step_id!r} references parameter {exc.args[0]!r} which was not "
            "supplied at replay time.",
            step_id=step.step_id,
        ) from exc
    return ResolvedStep(step=step, target=target, value=value, url=url)


def _match_error_mapping(
    rules: list[ErrorMappingRule], observation: Observation
) -> ErrorMappingRule | None:
    banner_text = " ".join(observation.banner_messages).lower()
    for rule in rules:
        if rule.match_kind == "banner_text_contains" and rule.match_value.lower() in banner_text:
            return rule
        if rule.match_kind == "url_contains" and rule.match_value.lower() in observation.url.lower():
            return rule
        if (
            rule.match_kind == "text_contains"
            and rule.match_value.lower() in observation.visible_text.lower()
        ):
            return rule
    return None


class ReplayEngine:
    """Executes one :class:`CapabilityArtifact` against a live surface.

    Never touches an LLM. Every decision here is a deterministic function of
    the artifact + the page state observed through ``surface``.
    """

    def __init__(
        self,
        surface: SurfaceAdapter,
        *,
        safety_policy: SafetyPolicy,
        retry_policy: RetryPolicy | None = None,
        evidence: EvidenceWriter | None = None,
    ) -> None:
        self.surface = surface
        self.safety_policy = safety_policy
        self.retry_policy = retry_policy or RetryPolicy()
        self.evidence = evidence
        self._run_id: str = ""

    def _log(self, event_type: EventType, run_id: str | None = None, **fields: object) -> None:
        if not self.evidence:
            return
        self.evidence.record_event(
            Event(run_id=run_id or self._run_id, session_id=self.surface.session.session_id,
                  event_type=event_type, **fields)  # type: ignore[arg-type]
        )

    async def run(
        self,
        artifact: CapabilityArtifact,
        params: dict[str, str],
        *,
        run_id: str | None = None,
        locator_profile_id: str | None = None,
    ) -> ReplayResult:
        run_id = run_id or str(uuid.uuid4())
        self._run_id = run_id
        started = time.monotonic()

        # 1. Validate artifact (defense in depth - the store already
        #    validates on load, but replay must never trust a caller-supplied
        #    artifact blindly).
        validate_artifact(artifact)

        # 2. Resolve inputs: every required parameter must be present.
        missing = [p.name for p in artifact.inputs if p.required and p.name not in params]
        if missing:
            return self._finish(
                run_id, started, artifact,
                ReplayStatus.HARD_FAILURE, ErrorCode.PARAMETER_RESOLUTION_FAILED,
                f"Missing required input parameter(s): {missing}", [], 0,
            )

        try:
            start_url = resolve_template(artifact.start_url_template, params)
        except KeyError as exc:
            return self._finish(
                run_id, started, artifact,
                ReplayStatus.HARD_FAILURE, ErrorCode.PARAMETER_RESOLUTION_FAILED,
                f"start_url_template references undeclared parameter {exc.args[0]!r}", [], 0,
            )

        self._log(EventType.RUN_STARTED, run_id, details={
            "capability_id": artifact.capability_id, "version": artifact.version, "params": {
                k: ("<redacted>" if "id" not in k else v) for k, v in params.items()
            }
        })

        await self.surface.start_session(start_url)
        output_types = {o.name: o.type for o in artifact.outputs}

        total_retries = 0
        restart_attempt = 0
        while True:
            restart_attempt += 1
            try:
                return await self._run_all_steps(
                    artifact, params, start_url, locator_profile_id, output_types,
                    run_id, started, total_retries,
                )
            except _RestartCapability as signal:
                total_retries += 1
                self._log(EventType.RETRY_ATTEMPTED, run_id, details={
                    "restart_attempt": restart_attempt, "error_code": signal.error.code.value,
                    "reason": "full capability restart after recoverable condition",
                })
                if restart_attempt >= self.retry_policy.max_attempts:
                    return self._finish(
                        run_id, started, artifact, ReplayStatus.HARD_FAILURE, signal.error.code,
                        f"Recovery exhausted after {restart_attempt} attempt(s): {signal.error.message}",
                        [], total_retries,
                    )
                await self.surface.navigate(start_url)
                continue

    async def _run_all_steps(
        self,
        artifact: CapabilityArtifact,
        params: dict[str, str],
        start_url: str,
        locator_profile_id: str | None,
        output_types: dict[str, ParamType],
        run_id: str,
        started: float,
        total_retries: int,
    ) -> ReplayResult:
        step_outcomes: list[StepOutcome] = []
        outputs: dict[str, object] = {}

        for step in artifact.steps:
            resolved = _resolve_step(step, params, artifact, locator_profile_id)
            attempt = 0
            step_started = time.monotonic()

            while True:
                attempt += 1
                try:
                    # Safety policy applies to every replayed action too -
                    # an artifact is not a trusted bypass of the policy layer.
                    current_url = await self.surface.current_url()
                    if resolved.target is not None or step.action == ActionType.NAVIGATE:
                        pseudo_action = AgentAction(
                            action=step.action,
                            reasoning="replay",
                            target=resolved.target,
                            value=resolved.value,
                            url=resolved.url,
                            output_name=step.output_name,
                        )
                        decision = self.safety_policy.evaluate(pseudo_action, current_url=current_url)
                        self._log(EventType.POLICY_DECISION, run_id, step_id=step.step_id,
                                   status="allowed" if decision.allowed else "blocked",
                                   details={"reason": decision.reason, "risk": decision.risk_level.value})
                        if not decision.allowed:
                            step_outcomes.append(StepOutcome(
                                step_id=step.step_id, action=step.action.value, status="blocked",
                                duration_ms=(time.monotonic() - step_started) * 1000,
                                attempts=attempt, error_code=ErrorCode.ACTION_BLOCKED_BY_POLICY.value,
                                error_message=decision.reason,
                            ))
                            return self._finish(
                                run_id, started, artifact, ReplayStatus.ESCALATED,
                                ErrorCode.ACTION_BLOCKED_BY_POLICY, decision.reason,
                                step_outcomes, total_retries,
                            )

                    extracted = await self._execute_action(step, resolved)

                    checkpoint_results = await self._run_checkpoints(step, artifact, extracted, params)
                    all_passed = all(c.passed for c in checkpoint_results)

                    if not all_passed:
                        raise HardFailureError(
                            ErrorCode.CHECKPOINT_FAILED,
                            f"Checkpoint(s) failed for step {step.step_id!r}: "
                            f"{[c.detail for c in checkpoint_results if not c.passed]}",
                            step_id=step.step_id,
                        )

                    if step.action == ActionType.EXTRACT and step.output_name:
                        out_type = output_types.get(step.output_name, ParamType.STRING)
                        outputs[step.output_name] = parse_typed_output(
                            extracted or "", out_type, output_name=step.output_name
                        )

                    step_outcomes.append(StepOutcome(
                        step_id=step.step_id, action=step.action.value, status="success",
                        duration_ms=(time.monotonic() - step_started) * 1000, attempts=attempt,
                        checkpoints=checkpoint_results,
                    ))
                    self._log(EventType.ACTION_EXECUTED, run_id, step_id=step.step_id,
                               action=step.action.value, status="success")
                    break  # step succeeded, move to next step

                except AutomationError as err:
                    # Reclassify via the artifact's error_mapping regardless
                    # of WHERE the failure surfaced - a checkpoint failing
                    # after a successful action, or (just as commonly) the
                    # action itself failing because its target never
                    # rendered (e.g. "click the view-member link" fails with
                    # a generic locator timeout when the real cause is that
                    # no member matched the search). Checking here, once,
                    # covers both - a business/recoverable condition should
                    # never be reported as a raw locator failure just
                    # because of which step happened to trip over it first.
                    if err.category != ErrorCategory.BUSINESS_OUTCOME:
                        observation = await self.surface.observe()
                        matched = _match_error_mapping(artifact.error_mapping, observation)
                        if matched:
                            err = _error_from_rule(matched, step.step_id)

                    self._log(EventType.ERROR, run_id, step_id=step.step_id,
                               error_code=err.code.value, status="failed",
                               details={"message": err.message, "category": err.category.value})

                    # Business outcome: not a bug, stop the run and report it.
                    if err.category == ErrorCategory.BUSINESS_OUTCOME:
                        step_outcomes.append(StepOutcome(
                            step_id=step.step_id, action=step.action.value, status="business_outcome",
                            duration_ms=(time.monotonic() - step_started) * 1000, attempts=attempt,
                            error_code=err.code.value, error_message=err.message,
                        ))
                        return self._finish(
                            run_id, started, artifact, ReplayStatus.BUSINESS_OUTCOME,
                            err.code, err.message, step_outcomes, total_retries,
                        )

                    # Recoverable + needs a full restart (e.g. session
                    # timeout): unwind entirely - re-running just the failed
                    # step would be wrong, since everything the earlier
                    # steps established (logged in, on the search page) is
                    # no longer true. Bounded by run()'s restart_attempt loop.
                    if err.code in _RECOVERABLE_VIA_FULL_RESTART:
                        raise _RestartCapability(err) from err

                    # Recoverable, in-place: bounded retry of just this step
                    # (e.g. an element that hasn't finished rendering yet).
                    if self.retry_policy.should_retry(err, attempt):
                        total_retries += 1
                        self._log(EventType.RETRY_ATTEMPTED, run_id, step_id=step.step_id,
                                   details={"attempt": attempt, "error_code": err.code.value})
                        continue  # retry the same step

                    # Retries exhausted or not retryable -> hard failure/escalation.
                    step_outcomes.append(StepOutcome(
                        step_id=step.step_id, action=step.action.value, status="failed",
                        duration_ms=(time.monotonic() - step_started) * 1000, attempts=attempt,
                        error_code=err.code.value, error_message=err.message,
                    ))
                    final_status = (
                        ReplayStatus.ESCALATED
                        if err.category == ErrorCategory.ESCALATED
                        else ReplayStatus.HARD_FAILURE
                    )
                    return self._finish(
                        run_id, started, artifact, final_status, err.code, err.message,
                        step_outcomes, total_retries,
                    )

                except Exception as exc:  # noqa: BLE001 - last-resort containment
                    # Anything reaching here is a defect in this engine or an
                    # unclassified surface failure (e.g. a raw Playwright
                    # error). It must never propagate as a bare traceback out
                    # of a deterministic engine - it is reported as a typed
                    # hard failure instead.
                    message = f"Unhandled {exc.__class__.__name__}: {exc}"
                    self._log(EventType.ERROR, run_id, step_id=step.step_id,
                               error_code=ErrorCode.INTERNAL_REPLAY_ERROR.value, status="failed",
                               details={"message": message})
                    step_outcomes.append(StepOutcome(
                        step_id=step.step_id, action=step.action.value, status="failed",
                        duration_ms=(time.monotonic() - step_started) * 1000, attempts=attempt,
                        error_code=ErrorCode.INTERNAL_REPLAY_ERROR.value, error_message=message,
                    ))
                    return self._finish(
                        run_id, started, artifact, ReplayStatus.HARD_FAILURE,
                        ErrorCode.INTERNAL_REPLAY_ERROR, message, step_outcomes, total_retries,
                    )

        return self._finish(
            run_id, started, artifact, ReplayStatus.SUCCESS, None,
            "Capability completed successfully.", step_outcomes, total_retries, outputs=outputs,
        )

    async def _execute_action(self, step: CapabilityStep, resolved: ResolvedStep) -> str | None:
        # CapabilityStep's own validator guarantees `target` is set for every
        # action type handled below (see app.artifacts.schema); asserting it
        # here narrows the type without weakening SurfaceAdapter's contract.
        action = step.action
        if action == ActionType.CLICK:
            assert resolved.target is not None
            await self.surface.click(resolved.target)
            return None
        if action == ActionType.FILL:
            assert resolved.target is not None
            await self.surface.fill(resolved.target, resolved.value or "")
            return None
        if action == ActionType.SELECT:
            assert resolved.target is not None
            await self.surface.select(resolved.target, resolved.value or "")
            return None
        if action == ActionType.EXTRACT:
            assert resolved.target is not None
            return await self.surface.extract(resolved.target)
        if action == ActionType.WAIT:
            assert resolved.target is not None
            ok = await self.surface.wait_for(resolved.target, timeout_ms=5000)
            if not ok:
                raise RecoverableError(
                    ErrorCode.TRANSIENT_LOAD_STATE,
                    f"Timed out waiting for element in step {step.step_id!r}",
                    step_id=step.step_id,
                )
            return None
        if action == ActionType.NAVIGATE:
            await self.surface.navigate(resolved.url or "")
            return None
        raise HardFailureError(
            ErrorCode.UNSUPPORTED_ACTION,
            f"Replay does not support action type {action} (step {step.step_id!r})",
            step_id=step.step_id,
        )

    async def _run_checkpoints(
        self,
        step: CapabilityStep,
        artifact: CapabilityArtifact,
        extracted_value: str | None,
        params: dict[str, str],
    ) -> list[CheckpointResult]:
        if not step.checkpoint_ids:
            return []
        observation = await self.surface.observe()
        current_url = await self.surface.current_url()
        results = []
        for cp_id in step.checkpoint_ids:
            checkpoint = artifact.checkpoint_by_id(cp_id)
            if checkpoint.target is not None:
                checkpoint = checkpoint.model_copy(
                    update={"target": _resolve_locator_params(checkpoint.target, params)}
                )
            result = await evaluate_checkpoint(
                checkpoint,
                surface=self.surface,
                current_url=current_url,
                page_text=observation.visible_text,
                extracted_value=extracted_value,
            )
            self._log(EventType.CHECKPOINT_EVALUATED, step_id=step.step_id,
                       status="passed" if result.passed else "failed",
                       details={"checkpoint_id": cp_id, "detail": result.detail})
            results.append(result)
        return results

    def _finish(
        self,
        run_id: str,
        started: float,
        artifact: CapabilityArtifact,
        status: ReplayStatus,
        code: ErrorCode | None,
        message: str,
        steps: list[StepOutcome],
        retries: int,
        outputs: dict[str, object] | None = None,
    ) -> ReplayResult:
        duration_ms = (time.monotonic() - started) * 1000
        result = ReplayResult(
            status=status, capability_id=artifact.capability_id, version=artifact.version,
            code=code.value if code else None, message=message, outputs=outputs or {},
            steps=steps, total_retries=retries, duration_ms=duration_ms,
            evidence_ref=str(self.evidence.run_dir) if self.evidence else None, run_id=run_id,
        )
        self._log(EventType.RUN_FINISHED, run_id, status=status.value,
                   duration_ms=duration_ms, details={"code": result.code})
        return result


def _error_from_rule(rule: ErrorMappingRule, step_id: str) -> AutomationError:
    from app.errors import BUSINESS_OUTCOME_CODES, RETRYABLE_CODES

    if rule.error_code in BUSINESS_OUTCOME_CODES:
        return BusinessOutcomeError(rule.error_code, rule.message, step_id=step_id)
    if rule.error_code in RETRYABLE_CODES:
        return RecoverableError(rule.error_code, rule.message, step_id=step_id)
    return HardFailureError(rule.error_code, rule.message, step_id=step_id)
