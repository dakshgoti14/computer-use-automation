"""Test doubles for :class:`app.providers.base.LLMProvider`.

``CountingLLMProvider`` exists specifically to make the "replay makes zero
LLM calls" guarantee mechanically checkable (see tests/unit/test_zero_llm_replay.py)
rather than something asserted only in prose.
"""

from __future__ import annotations

from collections.abc import Callable

from app.agent.models import AgentDecision


class ScriptedLLMProvider:
    """Returns a pre-programmed sequence of decisions.

    Used by agent-loop unit/integration tests where the real Gemini API
    would be slow, non-deterministic, and require network + credentials.
    """

    def __init__(self, decisions: list[AgentDecision]) -> None:
        self._decisions = list(decisions)
        self._index = 0
        self.call_count = 0

    async def decide(
        self,
        *,
        goal: str,
        observation_text: str,
        history_text: str,
        allowed_actions: list[str],
        **_: object,
    ) -> AgentDecision:
        self.call_count += 1
        if self._index >= len(self._decisions):
            raise IndexError(
                f"ScriptedLLMProvider exhausted after {self._index} calls "
                "- the agent loop asked for more decisions than were scripted"
            )
        decision = self._decisions[self._index]
        self._index += 1
        return decision


class CountingLLMProvider:
    """Wraps any provider and exposes ``call_count`` for structural proofs.

    Also usable standalone as a "provider" that must never be called: pass
    ``forbid_calls=True`` and it raises immediately if ``decide`` is invoked,
    which is exactly the assertion ``test_replay_makes_zero_llm_calls`` needs.
    """

    def __init__(
        self,
        delegate_factory: Callable[[], AgentDecision] | None = None,
        *,
        forbid_calls: bool = False,
    ) -> None:
        self._delegate_factory = delegate_factory
        self._forbid_calls = forbid_calls
        self.call_count = 0

    async def decide(self, **kwargs: object) -> AgentDecision:
        self.call_count += 1
        if self._forbid_calls:
            raise AssertionError(
                "CountingLLMProvider.decide() was called, but this provider was "
                "configured with forbid_calls=True. Deterministic replay must "
                "never call an LLMProvider."
            )
        if self._delegate_factory is None:
            raise RuntimeError("CountingLLMProvider has no delegate configured")
        return self._delegate_factory()
