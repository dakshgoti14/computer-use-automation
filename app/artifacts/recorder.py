"""Turns a successful discovery run into a reusable, parameterized artifact.

This is the module that enforces the core architectural rule: the artifact
it produces is built from *typed action records* (what happened), never
from the raw LLM conversation. The recorder never stores prompts or model
text - callers that want the transcript for audit purposes keep it in
evidence separately (see scripts/discover_capability.py), completely
decoupled from this object.

Parameterization strategy: the caller tells the recorder which literal
values correspond to which declared input parameter (e.g. the literal
"12345" used during this run corresponds to input ``member_id``). The
recorder replaces *exact* occurrences of that literal in fill values, URLs,
AND locator fields (test_id/name/label/text/css) with the ``${member_id}``
reference - so a row selected via e.g. ``test_id="view-member-12345"``
becomes reusable as ``test_id="view-member-${member_id}"`` rather than
silently overfitting to this one discovery run. This is a controlled,
narrow substitution over known values - not a blind global string replace -
so it cannot accidentally template unrelated text that happens to contain
the same substring in a different field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agent.models import ActionType, AgentAction
from app.artifacts.schema import (
    CapabilityArtifact,
    CapabilityStep,
    Checkpoint,
    CheckpointKind,
    ErrorMappingRule,
    OutputSpec,
    ParameterSpec,
    ParamType,
    SafetySpec,
)
from app.browser.locators import LocatorTarget
from app.errors import ErrorCode

_MONEY_PATTERN = r"^-?\$?\d{1,3}(,\d{3})*(\.\d{2})?$"
_NUMBER_PATTERN = r"^-?\d+(\.\d+)?$"


@dataclass
class RecordedStep:
    """One successfully executed action, captured during discovery."""

    step_id: str
    action: AgentAction
    description: str
    url_before: str
    url_after: str
    extracted_value: str | None = None


@dataclass
class DiscoveryRecorder:
    capability_id: str
    description: str
    inputs: list[ParameterSpec]
    outputs: list[OutputSpec]
    param_values: dict[str, str]  # literal value used during THIS run, by input name
    allowed_domains: tuple[str, ...]
    start_url: str
    discovery_run_id: str | None = None
    _steps: list[RecordedStep] = field(default_factory=list)

    def record(
        self,
        *,
        action: AgentAction,
        description: str,
        url_before: str,
        url_after: str,
        extracted_value: str | None = None,
    ) -> None:
        step_id = f"step-{len(self._steps) + 1:02d}"
        self._steps.append(
            RecordedStep(
                step_id=step_id,
                action=action,
                description=description,
                url_before=url_before,
                url_after=url_after,
                extracted_value=extracted_value,
            )
        )

    def _templatize(self, value: str) -> str:
        result = value
        for name, literal in self.param_values.items():
            if literal and literal in result:
                result = result.replace(literal, f"${{{name}}}")
        return result

    def _templatize_target_required(self, target: LocatorTarget) -> LocatorTarget:
        """Apply the same literal-to-``${param}`` substitution to a
        locator's own text fields.

        Without this, a target discovered against one specific run (e.g.
        ``test_id="view-member-12345"``) would be replayed verbatim and
        break for any other ``member_id`` - this is what makes
        ``test_id="view-member-${member_id}"`` come out of discovery instead.
        Mirrors :func:`app.replay.executor._resolve_locator_params`, which
        performs the inverse substitution at replay time.
        """

        return target.model_copy(
            update={
                "test_id": self._templatize(target.test_id) if target.test_id else target.test_id,
                "name": self._templatize(target.name) if target.name else target.name,
                "label": self._templatize(target.label) if target.label else target.label,
                "text": self._templatize(target.text) if target.text else target.text,
                "css": self._templatize(target.css) if target.css else target.css,
                "fallbacks": [self._templatize_target_required(fb) for fb in target.fallbacks],
            }
        )

    def _templatize_target(self, target: LocatorTarget | None) -> LocatorTarget | None:
        if target is None:
            return None
        return self._templatize_target_required(target)

    def _pattern_for_type(self, param_type: ParamType) -> str:
        return {
            ParamType.MONEY: _MONEY_PATTERN,
            ParamType.NUMBER: _NUMBER_PATTERN,
        }.get(param_type, r".+")

    def finalize(self) -> CapabilityArtifact:
        if not self._steps:
            raise ValueError("Cannot finalize an artifact with zero recorded steps")

        output_types = {o.name: o.type for o in self.outputs}
        steps: list[CapabilityStep] = []
        checkpoints: list[Checkpoint] = []

        for recorded in self._steps:
            action = recorded.action
            value_template = self._templatize(action.value) if action.value else None
            url_template = self._templatize(action.url) if action.url else None
            templated_target = self._templatize_target(action.target)
            checkpoint_ids: list[str] = []

            # Rule A: if the URL changed as a result of this step, record an
            # explicit, executable post-condition rather than trusting that
            # "the click probably worked".
            if recorded.url_after != recorded.url_before:
                cp_id = f"cp-{recorded.step_id}-url"
                pattern = re.escape(self._templatize(recorded.url_after))
                # Re-expand templated param refs into a permissive wildcard so
                # the checkpoint still matches when replayed with a different
                # parameter value.
                for name in self.param_values:
                    pattern = pattern.replace(re.escape(f"${{{name}}}"), r"[^/]+")
                checkpoints.append(
                    Checkpoint(
                        checkpoint_id=cp_id,
                        description=f"Page navigated after {recorded.description}",
                        kind=CheckpointKind.URL_MATCHES,
                        url_pattern=pattern,
                    )
                )
                checkpoint_ids.append(cp_id)

            # Rule B: extract steps get a value-shape checkpoint driven by the
            # declared output type, so a malformed/garbage extraction is
            # caught explicitly rather than returned silently.
            if action.action == ActionType.EXTRACT and action.output_name:
                out_type = output_types.get(action.output_name, ParamType.STRING)
                cp_id = f"cp-{recorded.step_id}-value"
                checkpoints.append(
                    Checkpoint(
                        checkpoint_id=cp_id,
                        description=(
                            f"Extracted value for '{action.output_name}' matches "
                            f"the expected {out_type.value} shape"
                        ),
                        kind=CheckpointKind.VALUE_MATCHES_PATTERN,
                        value_pattern=self._pattern_for_type(out_type),
                    )
                )
                checkpoint_ids.append(cp_id)

            # Rule C: every step's own target must be visible for it to have
            # executed at all - make that an explicit, named checkpoint too
            # (not just an implicit locator-resolution side effect). Only
            # when this step did NOT navigate away (Rule A already covers
            # that case): asserting a just-clicked link's target is "still
            # visible" is nonsensical once the click has navigated past it.
            if action.target is not None and recorded.url_after == recorded.url_before:
                cp_id = f"cp-{recorded.step_id}-target"
                checkpoints.append(
                    Checkpoint(
                        checkpoint_id=cp_id,
                        description=f"Target element present for: {recorded.description}",
                        kind=CheckpointKind.ELEMENT_VISIBLE,
                        target=templated_target,
                    )
                )
                checkpoint_ids.append(cp_id)

            steps.append(
                CapabilityStep(
                    step_id=recorded.step_id,
                    description=recorded.description,
                    action=action.action,
                    target=templated_target,
                    value_template=value_template,
                    url_template=url_template,
                    output_name=action.output_name,
                    checkpoint_ids=checkpoint_ids,
                )
            )

        # These are sensible starting-point rules, not something inferred from
        # what discovery actually observed (a successful discovery run that
        # found its target never sees the "not found" banner at all, so
        # there is nothing recorded to derive this from). A human reviewing
        # the generated artifact - which the schema is explicitly designed
        # to make easy - should verify these against the target
        # application's actual copy and adjust as needed; see REPORT.md
        # "Cuts" for a real example of a mismatch this caught (this demo
        # app's actual banner text is "No members found...", not "not
        # found" - a substring that never matched).
        error_mapping = [
            ErrorMappingRule(
                match_kind="banner_text_contains",
                match_value="no members found",
                error_code=ErrorCode.MEMBER_NOT_FOUND,
                message="The application reported that no matching member exists.",
            ),
            ErrorMappingRule(
                match_kind="banner_text_contains",
                match_value="session has expired",
                error_code=ErrorCode.SESSION_TIMEOUT,
                message="The application session expired and requires re-authentication.",
            ),
            ErrorMappingRule(
                match_kind="text_contains",
                match_value="unexpected error",
                error_code=ErrorCode.UNEXPECTED_APPLICATION_ERROR,
                message="The application reported an unexpected internal error.",
            ),
        ]

        return CapabilityArtifact(
            capability_id=self.capability_id,
            version=1,
            description=self.description,
            start_url_template=self._templatize(self.start_url),
            inputs=self.inputs,
            outputs=self.outputs,
            preconditions=["User session must be authenticated against the target application."],
            steps=steps,
            checkpoints=checkpoints,
            error_mapping=error_mapping,
            safety=SafetySpec(allowed_domains=self.allowed_domains),
            discovery_run_id=self.discovery_run_id,
        )
