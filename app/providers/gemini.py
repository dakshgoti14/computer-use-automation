"""Gemini implementation of :class:`app.providers.base.LLMProvider`.

Uses the official ``google-genai`` SDK with JSON structured output
constrained to :class:`AgentDecision`'s schema, so the model cannot return
free-form prose that would need fragile regex parsing.
"""

from __future__ import annotations

import asyncio
import json
import logging

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.agent.models import AgentDecision
from app.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from app.errors import ErrorCode, HardFailureError

logger = logging.getLogger(__name__)

#: Every call is bounded - an unbounded network call inside the discovery
#: loop would hang the whole run indefinitely on a slow/stuck connection.
#: Discovered the hard way: an early real run against a congested API
#: endpoint hung with no error for several minutes before this was added.
_REQUEST_TIMEOUT_MS = 45_000

#: Bounded retry for transient server-side unavailability (HTTP 503/504 -
#: "high demand", deadline exceeded). Observed for real during development:
#: identical requests failed then succeeded seconds later with no change on
#: our end. Never retries a 4xx (bad request, invalid key, quota exhausted -
#: those are not transient and retrying them wastes the attempt budget).
_MAX_PROVIDER_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (1.0, 3.0)


class GeminiProvider:
    """Discovery-only LLM provider backed by the Gemini API.

    Never imported by app.replay.* - see that package's module docstring.
    """

    def __init__(self, *, api_key: str, model: str) -> None:
        # api_key is held only in-memory by the SDK client; never logged.
        self._client = genai.Client(api_key=api_key)
        self._model = model

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
        user_prompt = build_user_prompt(
            goal=goal,
            observation_text=observation_text,
            history_text=history_text,
            step_number=step_number,
            max_steps=max_steps,
        )
        response = await self._generate_with_retry(user_prompt)

        raw_text = response.text
        if not raw_text:
            raise HardFailureError(
                ErrorCode.INVALID_AGENT_DECISION,
                "Gemini returned an empty response",
            )
        try:
            payload = json.loads(raw_text)
            return AgentDecision.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            raise HardFailureError(
                ErrorCode.INVALID_AGENT_DECISION,
                f"Gemini response did not match the AgentDecision schema: {exc}",
                context={"raw_response": raw_text[:500]},
            ) from exc

    async def _generate_with_retry(self, user_prompt: str) -> types.GenerateContentResponse:
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_PROVIDER_ATTEMPTS + 1):
            try:
                return await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=AgentDecision,
                        temperature=0.0,
                        http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS),
                    ),
                )
            except genai_errors.ServerError as exc:
                # 5xx - transient server-side unavailability. Retry.
                last_exc = exc
                if attempt < _MAX_PROVIDER_ATTEMPTS:
                    logger.warning(
                        "Gemini call attempt %d/%d failed with a transient server "
                        "error, retrying: %s",
                        attempt, _MAX_PROVIDER_ATTEMPTS, exc.__class__.__name__,
                    )
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
            except Exception as exc:  # noqa: BLE001 - everything else fails immediately
                # 4xx client errors (bad request, invalid key, quota exhausted)
                # are not transient - retrying wastes the attempt budget and
                # hides a real configuration problem.
                raise HardFailureError(
                    ErrorCode.LLM_PROVIDER_ERROR,
                    f"Gemini API call failed: {exc.__class__.__name__}",
                    context={"detail": str(exc)},
                ) from exc

        assert last_exc is not None
        raise HardFailureError(
            ErrorCode.LLM_PROVIDER_ERROR,
            f"Gemini API call failed after {_MAX_PROVIDER_ATTEMPTS} attempts "
            f"(transient server errors): {last_exc.__class__.__name__}",
            context={"detail": str(last_exc)},
        ) from last_exc
