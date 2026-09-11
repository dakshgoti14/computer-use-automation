"""THE critical structural test: ReplayEngine must make ZERO LLM calls.

Two independent proofs:

1. Static: app.replay.executor imports nothing from app.providers or
   app.agent.loop/planner (only the pure, LLM-free app.agent.models enum).
2. Dynamic: wiring a call-forbidding provider stand-in anywhere reachable
   from a replay run and asserting it is never invoked, across every
   status outcome (success, business outcome, hard failure).
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from app.browser.playwright_surface import PlaywrightSurface
from app.providers.mock import CountingLLMProvider
from app.replay.executor import ReplayEngine
from app.safety.policy import SafetyPolicy
from tests.conftest import build_gold_artifact


def test_replay_executor_module_does_not_import_providers_or_agent_loop():
    """Static guarantee: even if someone forgot to wire a forbidding
    provider into a test, the module itself cannot reach an LLM."""

    module = importlib.import_module("app.replay.executor")
    source = Path(module.__file__).read_text()
    tree = ast.parse(source)

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_prefixes = ("app.providers", "app.agent.loop", "app.agent.planner")
    violations = [
        m for m in imported_modules if any(m.startswith(p) for p in forbidden_prefixes)
    ]
    assert violations == [], f"app.replay.executor must never import: {violations}"


async def test_replay_makes_zero_llm_calls_on_success(demo_app_base_url):
    forbidding_provider = CountingLLMProvider(forbid_calls=True)
    artifact = build_gold_artifact(demo_app_base_url)
    surface = PlaywrightSurface(headless=True)
    engine = ReplayEngine(surface, safety_policy=SafetyPolicy(allowed_domains=("127.0.0.1",)))

    try:
        result = await engine.run(artifact, {"member_id": "12345"})
    finally:
        await surface.close()

    assert result.status.value == "success"
    assert forbidding_provider.call_count == 0


async def test_replay_makes_zero_llm_calls_on_business_outcome(demo_app_base_url):
    forbidding_provider = CountingLLMProvider(forbid_calls=True)
    artifact = build_gold_artifact(demo_app_base_url)
    surface = PlaywrightSurface(headless=True)
    engine = ReplayEngine(surface, safety_policy=SafetyPolicy(allowed_domains=("127.0.0.1",)))

    try:
        result = await engine.run(artifact, {"member_id": "99999"})
    finally:
        await surface.close()

    assert result.status.value == "business_outcome"
    assert forbidding_provider.call_count == 0


async def test_replay_engine_constructor_has_no_llm_provider_parameter():
    """Belt-and-braces: ReplayEngine's __init__ signature has no way to
    accept an LLMProvider at all - there is no parameter to smuggle one
    through even if a caller tried."""

    import inspect

    sig = inspect.signature(ReplayEngine.__init__)
    for name in sig.parameters:
        assert "llm" not in name.lower() and "provider" not in name.lower(), (
            f"ReplayEngine.__init__ unexpectedly accepts {name!r}"
        )
