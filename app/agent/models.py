"""Typed action vocabulary the LLM is constrained to.

The LLM never generates code and never picks an arbitrary action name - it
fills in this fixed schema. :class:`AgentDecision` is what
:mod:`app.providers` implementations must return, and what
:mod:`app.agent.planner` validates before anything is allowed to execute.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.browser.locators import (
    REQUIRED_FIELDS_BY_STRATEGY,
    LocatorStrategyKind,
    LocatorTarget,
)


class ActionType(str, Enum):
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    EXTRACT = "extract"
    WAIT = "wait"
    NAVIGATE = "navigate"  # only allowed when safety policy permits
    FINISH = "finish"
    ESCALATE = "escalate"


#: Actions that must carry a target locator.
_ACTIONS_REQUIRING_TARGET = {
    ActionType.CLICK,
    ActionType.FILL,
    ActionType.SELECT,
    ActionType.EXTRACT,
    ActionType.WAIT,
}


class LocatorTargetInput(BaseModel):
    """Wire-format locator for LLM structured output.

    Identical in shape to :class:`LocatorTarget` but without the recursive
    ``fallbacks`` field - structured-output JSON schemas (Gemini included)
    do not support recursive models. The live agent decides one locator per
    step; fallback chains are a replay/artifact-time concern, added later by
    the discovery recorder, not something the LLM itself needs to author.
    """

    strategy: LocatorStrategyKind
    role: str | None = None
    name: str | None = None
    label: str | None = None
    test_id: str | None = None
    text: str | None = None
    css: str | None = None
    xpath: str | None = None
    x: float | None = None
    y: float | None = None

    @model_validator(mode="after")
    def _check_required_fields(self) -> LocatorTargetInput:
        for field_name in REQUIRED_FIELDS_BY_STRATEGY[self.strategy]:
            if getattr(self, field_name) in (None, ""):
                raise ValueError(
                    f"strategy={self.strategy} requires field '{field_name}' to be set"
                )
        return self

    def to_locator_target(self) -> LocatorTarget:
        return LocatorTarget(**self.model_dump(exclude={"nth"}, exclude_none=False))


def _validate_action_shape(
    action: ActionType,
    *,
    has_target: bool,
    value: str | None,
    url: str | None,
    output_name: str | None,
    finish_summary: str | None,
    escalation_reason: str | None,
) -> None:
    if action in _ACTIONS_REQUIRING_TARGET and not has_target:
        raise ValueError(f"action={action} requires a target locator")
    if action == ActionType.FILL and not value:
        raise ValueError("action=fill requires a non-empty value")
    if action == ActionType.SELECT and not value:
        raise ValueError("action=select requires a non-empty value")
    if action == ActionType.EXTRACT and not output_name:
        raise ValueError("action=extract requires output_name")
    if action == ActionType.NAVIGATE and not url:
        raise ValueError("action=navigate requires a url")
    if action == ActionType.FINISH and not finish_summary:
        raise ValueError("action=finish requires finish_summary")
    if action == ActionType.ESCALATE and not escalation_reason:
        raise ValueError("action=escalate requires escalation_reason")


class AgentDecision(BaseModel):
    """The exact wire schema an :class:`LLMProvider` must return.

    This is the *only* channel through which the LLM affects the system.
    There is no code-eval path, no shell access, and no free-form action
    name - every field is validated against the fixed vocabulary above.
    Uses :class:`LocatorTargetInput` (non-recursive) because this is what
    goes into a structured-output JSON schema request.
    """

    action: ActionType
    reasoning: str = Field(description="Short (<=200 char) rationale, kept for evidence")
    target: LocatorTargetInput | None = None
    value: str | None = Field(default=None, description="Value for fill/select")
    url: str | None = Field(default=None, description="Destination for navigate")
    output_name: str | None = Field(
        default=None, description="Logical name to store an extract() result under"
    )
    finish_summary: str | None = None
    escalation_reason: str | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> AgentDecision:
        _validate_action_shape(
            self.action,
            has_target=self.target is not None,
            value=self.value,
            url=self.url,
            output_name=self.output_name,
            finish_summary=self.finish_summary,
            escalation_reason=self.escalation_reason,
        )
        return self

    def to_agent_action(self) -> AgentAction:
        return AgentAction(
            action=self.action,
            reasoning=self.reasoning,
            target=self.target.to_locator_target() if self.target else None,
            value=self.value,
            url=self.url,
            output_name=self.output_name,
            finish_summary=self.finish_summary,
            escalation_reason=self.escalation_reason,
        )


class AgentAction(BaseModel):
    """The internal, executable form of a decision.

    Identical to :class:`AgentDecision` except ``target`` is a full
    :class:`LocatorTarget` (with a - possibly empty - fallback chain). This
    is what the safety policy, evidence writer, and surface adapter consume.
    """

    action: ActionType
    reasoning: str
    target: LocatorTarget | None = None
    value: str | None = None
    url: str | None = None
    output_name: str | None = None
    finish_summary: str | None = None
    escalation_reason: str | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> AgentAction:
        _validate_action_shape(
            self.action,
            has_target=self.target is not None,
            value=self.value,
            url=self.url,
            output_name=self.output_name,
            finish_summary=self.finish_summary,
            escalation_reason=self.escalation_reason,
        )
        return self
