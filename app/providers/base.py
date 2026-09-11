"""LLM provider abstraction.

The agent/discovery loop depends on this ``LLMProvider`` protocol only.
Gemini is one implementation; adding Anthropic/OpenAI/a test double later
means writing one new class here, not touching the agent loop.

Deterministic replay MUST NOT import anything from this package. That
structural boundary is what makes "replay makes zero LLM calls" enforceable
rather than just asserted - see app/replay/executor.py's module docstring.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agent.models import AgentDecision


@runtime_checkable
class LLMProvider(Protocol):
    """A provider that turns (goal, observation, history) into one decision."""

    async def decide(
        self,
        *,
        goal: str,
        observation_text: str,
        history_text: str,
        allowed_actions: list[str],
        step_number: int = 1,
        max_steps: int = 20,
    ) -> AgentDecision:
        """Return exactly one structured, schema-validated agent decision.

        Implementations must not return free-form prose - the caller only
        accepts a value that already satisfies :class:`AgentDecision`.
        """
        ...
