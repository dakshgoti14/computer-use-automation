"""Turns (goal, observation, history) into one validated, executable action.

This is the only place that talks to an :class:`LLMProvider` during
discovery. It never returns anything looser than :class:`AgentAction` - a
provider that returns malformed JSON or an out-of-vocabulary action raises a
typed error here rather than being passed through to the surface.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.agent.models import AgentAction
from app.errors import ErrorCode, HardFailureError
from app.providers.base import LLMProvider

_ALLOWED_ACTIONS = ["click", "fill", "select", "extract", "wait", "navigate", "finish", "escalate"]


class Planner:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def decide(
        self,
        *,
        goal: str,
        observation_text: str,
        history_text: str,
        step_number: int,
        max_steps: int,
    ) -> AgentAction:
        try:
            decision = await self._provider.decide(
                goal=goal,
                observation_text=observation_text,
                history_text=history_text,
                allowed_actions=_ALLOWED_ACTIONS,
                step_number=step_number,
                max_steps=max_steps,
            )
        except HardFailureError:
            raise
        except ValidationError as exc:
            raise HardFailureError(
                ErrorCode.INVALID_AGENT_DECISION,
                f"LLM provider returned a decision that failed schema validation: {exc}",
            ) from exc

        try:
            return decision.to_agent_action()
        except ValidationError as exc:
            raise HardFailureError(
                ErrorCode.INVALID_AGENT_DECISION,
                f"Decision could not be converted to an executable action: {exc}",
            ) from exc
