"""LLM provider registry and factory.

Only the discovery path (app.agent.loop.DiscoveryEngine, scripts/discover_capability.py)
should ever call :func:`create_llm_provider`. Deterministic replay must never
import this module - see app/replay/executor.py.
"""

from __future__ import annotations

from app.config import Settings
from app.errors import ErrorCode, HardFailureError
from app.providers.base import LLMProvider


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Instantiate the configured LLM provider.

    Raises a clear, typed configuration error if the selected provider is
    unusable (e.g. missing API key) rather than failing deep inside a call.
    """

    provider_name = settings.llm_provider.strip().lower()

    if provider_name == "gemini":
        from app.providers.gemini import GeminiProvider

        api_key = settings.require_gemini_api_key()
        return GeminiProvider(api_key=api_key, model=settings.gemini_model)

    if provider_name == "mock":
        from app.providers.mock import ScriptedLLMProvider

        return ScriptedLLMProvider(decisions=[])

    raise HardFailureError(
        ErrorCode.LLM_CONFIG_MISSING,
        f"Unknown LLM_PROVIDER={provider_name!r}. Supported: gemini, mock.",
    )


__all__ = ["LLMProvider", "create_llm_provider"]
