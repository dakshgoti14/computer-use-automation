#!/usr/bin/env python
"""Run a GENUINE Gemini-driven discovery session against the local demo app.

    python scripts/discover_capability.py \\
        --goal "Look up member 12345 and read their current savings balance"

This performs real observe -> decide (Gemini) -> validate -> act loop
against a live Chromium browser and the local demo application, then
records the successful path as a reusable, parameterized capability
artifact under capabilities/. It fails loudly (not silently, not with a
fabricated response) if GEMINI_API_KEY is not configured.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.loop import DiscoveryEngine, DiscoveryStatus  # noqa: E402
from app.agent.planner import Planner  # noqa: E402
from app.artifacts.schema import OutputSpec, ParameterSpec, ParamType  # noqa: E402
from app.artifacts.store import ArtifactStore  # noqa: E402
from app.browser.playwright_surface import PlaywrightSurface  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.errors import AutomationError  # noqa: E402
from app.observability.evidence import EvidenceWriter  # noqa: E402
from app.providers import create_llm_provider  # noqa: E402
from app.safety.policy import SafetyPolicy  # noqa: E402
from scripts._common import ensure_demo_app_running, print_json  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--goal", required=True,
        help='Natural-language goal, e.g. "Look up member 12345 and read their current savings balance"',
    )
    parser.add_argument("--capability-id", default="member_savings_lookup")
    parser.add_argument("--member-id", default="12345", help="Literal member id used during this run")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--start-url", default=None, help="Defaults to <demo_app_base_url>/login")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    settings = get_settings()

    try:
        provider = create_llm_provider(settings)
    except AutomationError as exc:
        print(f"CONFIGURATION ERROR: {exc.message}", file=sys.stderr)
        print("Set GEMINI_API_KEY in your .env file (see .env.example) and retry.", file=sys.stderr)
        return 2

    demo_proc = ensure_demo_app_running(settings.demo_app_base_url)
    start_url = args.start_url or f"{settings.demo_app_base_url}/login"

    import uuid

    surface = PlaywrightSurface(headless=settings.headless_browser)
    evidence = EvidenceWriter(
        evidence_root=settings.evidence_dir, run_kind="discovery", run_id=uuid.uuid4().hex,
    )
    engine = DiscoveryEngine(
        surface=surface,
        planner=Planner(provider),
        safety_policy=SafetyPolicy(allowed_domains=(settings.demo_app_host,)),
        evidence=evidence,
        max_steps=args.max_steps or settings.agent_max_steps,
    )

    print(f"[discover] goal: {args.goal}")
    print(f"[discover] provider: {settings.llm_provider} model: {settings.gemini_model}")
    print(f"[discover] start_url: {start_url}")
    print(f"[discover] evidence: {evidence.run_dir}")

    try:
        result = await engine.run(
            goal=args.goal,
            start_url=start_url,
            capability_id=args.capability_id,
            description=args.goal,
            inputs=[ParameterSpec(name="member_id", type=ParamType.STRING, required=True)],
            outputs=[OutputSpec(name="savings_balance", type=ParamType.MONEY)],
            param_values={"member_id": args.member_id},
            allowed_domains=(settings.demo_app_host,),
        )
    finally:
        await surface.close()
        if demo_proc:
            demo_proc.terminate()

    print(f"\n[discover] status: {result.status.value}")
    print(f"[discover] steps taken: {result.steps_taken}")
    print(f"[discover] message: {result.message}")

    if result.status == DiscoveryStatus.SUCCESS and result.artifact is not None:
        store = ArtifactStore(settings.capabilities_dir)
        path = store.save(result.artifact)
        print(f"\n[discover] SUCCESS - capability artifact saved to {path}")
        print_json(result.artifact.model_dump(mode="json"))
        return 0

    print("\n[discover] Did not produce a capability artifact.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
