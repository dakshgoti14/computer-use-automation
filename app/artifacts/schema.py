"""Strongly typed, versioned capability artifact schema.

Design goals (see REPORT.md "Artifact schema" for the full rationale):

* Independent of the LLM transcript that discovered it - a step is
  executable intent ("fill the member id field with ${member_id}"), never a
  quote of what the model said.
* Parameterized - literal values used during discovery (e.g. "12345") are
  replaced with named ``${param}`` references resolved at replay time via
  :func:`resolve_template`, never via blind string replacement.
* Reviewable - a human can read this JSON and understand exactly what will
  happen, in what order, and what would make each step fail.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.agent.models import ActionType
from app.browser.locators import LocatorTarget
from app.errors import ErrorCode

SCHEMA_VERSION = "1.0"

#: Matches ``${name}`` parameter references inside a template string.
_PARAM_REF_PATTERN = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class ParamType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    MONEY = "money"
    BOOLEAN = "boolean"


class ParameterSpec(BaseModel):
    name: str
    type: ParamType
    required: bool = True
    description: str | None = None


class OutputSpec(BaseModel):
    name: str
    type: ParamType
    description: str | None = None


class CheckpointKind(str, Enum):
    ELEMENT_VISIBLE = "element_visible"
    ELEMENT_NOT_VISIBLE = "element_not_visible"
    TEXT_CONTAINS = "text_contains"
    URL_MATCHES = "url_matches"
    VALUE_MATCHES_PATTERN = "value_matches_pattern"


class Checkpoint(BaseModel):
    """An executable assertion. A step only counts as successful once every
    checkpoint listed in its ``checkpoint_ids`` has passed."""

    checkpoint_id: str
    description: str
    kind: CheckpointKind
    target: LocatorTarget | None = None
    expected_text: str | None = None
    url_pattern: str | None = None
    value_pattern: str | None = None

    @model_validator(mode="after")
    def _check_required_fields(self) -> Checkpoint:
        if (
            self.kind in (CheckpointKind.ELEMENT_VISIBLE, CheckpointKind.ELEMENT_NOT_VISIBLE)
            and self.target is None
        ):
            raise ValueError(f"checkpoint kind {self.kind} requires a target")
        if self.kind == CheckpointKind.TEXT_CONTAINS and not self.expected_text:
            raise ValueError("checkpoint kind text_contains requires expected_text")
        if self.kind == CheckpointKind.URL_MATCHES and not self.url_pattern:
            raise ValueError("checkpoint kind url_matches requires url_pattern")
        if self.kind == CheckpointKind.VALUE_MATCHES_PATTERN and not self.value_pattern:
            raise ValueError("checkpoint kind value_matches_pattern requires value_pattern")
        return self


class CapabilityStep(BaseModel):
    """One executable, parameterized instruction.

    ``value_template``/``url_template`` may reference declared inputs via
    ``${param_name}``; they are never raw f-string-substituted, they go
    through :func:`resolve_template`, which fails closed on unknown refs.
    """

    step_id: str
    description: str
    action: ActionType
    target: LocatorTarget | None = None
    value_template: str | None = None
    url_template: str | None = None
    output_name: str | None = None
    checkpoint_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_required_fields(self) -> CapabilityStep:
        actions_requiring_target = {
            ActionType.CLICK,
            ActionType.FILL,
            ActionType.SELECT,
            ActionType.EXTRACT,
            ActionType.WAIT,
        }
        if self.action in actions_requiring_target and self.target is None:
            raise ValueError(f"step action={self.action} requires a target locator")
        if self.action == ActionType.FILL and not self.value_template:
            raise ValueError("step action=fill requires value_template")
        if self.action == ActionType.SELECT and not self.value_template:
            raise ValueError("step action=select requires value_template")
        if self.action == ActionType.EXTRACT and not self.output_name:
            raise ValueError("step action=extract requires output_name")
        if self.action == ActionType.NAVIGATE and not self.url_template:
            raise ValueError("step action=navigate requires url_template")
        if self.action in (ActionType.FINISH, ActionType.ESCALATE):
            raise ValueError(
                f"step action={self.action} is a discovery-only terminal action and "
                "cannot appear as a replayable capability step"
            )
        return self


class ErrorMappingRule(BaseModel):
    """Maps an observable page condition to a stable error/business code.

    ``match_kind`` intentionally mirrors what the checkpoint evaluator can
    already observe (banner text, URL, page kind) so replay does not need
    any new inspection machinery to classify an outcome.
    """

    match_kind: Literal["banner_text_contains", "url_contains", "text_contains"]
    match_value: str
    error_code: ErrorCode
    message: str


class SafetySpec(BaseModel):
    allowed_domains: tuple[str, ...]
    navigation_allowed: bool = True
    max_risk_level: Literal["safe", "restricted"] = "safe"


class LocatorProfile(BaseModel):
    """A named override set of locators for a specific UI variant/tenant.

    Lets the same capability_id run against Variant A vs Variant B of the
    demo app (or, conceptually, different bank vendors) without duplicating
    the capability: only the profile's per-step target overrides differ.
    See REPORT.md "Heterogeneity & multi-tenant".
    """

    profile_id: str
    description: str
    step_target_overrides: dict[str, LocatorTarget] = Field(default_factory=dict)


class CapabilityArtifact(BaseModel):
    schema_version: str = SCHEMA_VERSION
    capability_id: str
    version: int = Field(ge=1)
    description: str
    start_url_template: str
    inputs: list[ParameterSpec] = Field(default_factory=list)
    outputs: list[OutputSpec] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    steps: list[CapabilityStep]
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    error_mapping: list[ErrorMappingRule] = Field(default_factory=list)
    safety: SafetySpec
    locator_profiles: list[LocatorProfile] = Field(default_factory=list)
    discovery_run_id: str | None = Field(
        default=None,
        description="Pointer to the discovery evidence run that produced this "
        "artifact. Intentionally NOT the raw transcript - see module docstring.",
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @field_validator("steps")
    @classmethod
    def _unique_step_ids(cls, steps: list[CapabilityStep]) -> list[CapabilityStep]:
        ids = [s.step_id for s in steps]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate step_id values: {ids}")
        return steps

    def input_names(self) -> set[str]:
        return {p.name for p in self.inputs}

    def checkpoint_by_id(self, checkpoint_id: str) -> Checkpoint:
        for cp in self.checkpoints:
            if cp.checkpoint_id == checkpoint_id:
                return cp
        raise KeyError(checkpoint_id)

    def locator_profile(self, profile_id: str) -> LocatorProfile | None:
        for profile in self.locator_profiles:
            if profile.profile_id == profile_id:
                return profile
        return None


def extract_param_refs(template: str) -> set[str]:
    return set(_PARAM_REF_PATTERN.findall(template))


def resolve_template(template: str, params: dict[str, str]) -> str:
    """Safely substitute ``${name}`` references. Fails closed.

    Unlike ``str.replace``/f-strings, this never partially matches and never
    silently leaves a reference unresolved: any ``${name}`` not present in
    ``params`` raises :class:`KeyError`, which the replay engine turns into a
    ``PARAMETER_RESOLUTION_FAILED`` hard failure.
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            raise KeyError(name)
        return str(params[name])

    return _PARAM_REF_PATTERN.sub(_sub, template)
