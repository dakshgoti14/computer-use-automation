#!/usr/bin/env python
"""Deterministically replay a saved capability artifact. Makes zero LLM calls.

    python scripts/replay_capability.py \\
        --capability capabilities/member_savings_lookup.json \\
        --member-id 12345

    python scripts/replay_capability.py \\
        --capability capabilities/member_savings_lookup.json \\
        --member-id 99999          # -> MEMBER_NOT_FOUND business outcome
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.artifacts.store import ArtifactStore  # noqa: E402
from app.browser.playwright_surface import PlaywrightSurface  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.observability.evidence import EvidenceWriter  # noqa: E402
from app.replay.executor import ReplayEngine  # noqa: E402
from app.replay.result import ReplayStatus  # noqa: E402
from app.safety.policy import SafetyPolicy  # noqa: E402
from scripts._common import ensure_demo_app_running, print_json  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability", required=True, help="Path to a capability artifact JSON file")
    parser.add_argument("--member-id", default=None, help="Shorthand for --param member_id=<value>")
    parser.add_argument(
        "--param", action="append", default=[],
        help="Additional input parameter as name=value (repeatable)",
    )
    parser.add_argument("--locator-profile", default=None)
    parser.add_argument("--run-kind", default="replay", help="Evidence subdirectory name")
    return parser.parse_args()


def _collect_params(args: argparse.Namespace) -> dict[str, str]:
    params: dict[str, str] = {}
    if args.member_id is not None:
        params["member_id"] = args.member_id
    for entry in args.param:
        if "=" not in entry:
            raise SystemExit(f"--param must be name=value, got {entry!r}")
        name, value = entry.split("=", 1)
        params[name] = value
    return params


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    params = _collect_params(args)

    store = ArtifactStore(settings.capabilities_dir)
    artifact = store.load_path(Path(args.capability))

    demo_proc = ensure_demo_app_running(settings.demo_app_base_url)

    run_id = uuid.uuid4().hex
    evidence = EvidenceWriter(evidence_root=settings.evidence_dir, run_kind=args.run_kind, run_id=run_id)
    surface = PlaywrightSurface(headless=settings.headless_browser)
    engine = ReplayEngine(
        surface,
        safety_policy=SafetyPolicy(allowed_domains=artifact.safety.allowed_domains),
        evidence=evidence,
    )

    print(f"[replay] capability: {artifact.capability_id} v{artifact.version}")
    print(f"[replay] params: {params}")
    print(f"[replay] evidence: {evidence.run_dir}")

    try:
        result = await engine.run(artifact, params, run_id=run_id, locator_profile_id=args.locator_profile)
    finally:
        await surface.close()
        if demo_proc:
            demo_proc.terminate()

    print(f"\n[replay] status: {result.status.value}")
    print(f"[replay] duration_ms: {result.duration_ms:.1f}")
    print(f"[replay] retries: {result.total_retries}")
    print(f"[replay] message: {result.message}")
    print_json(result.model_dump(mode="json"))

    return 0 if result.status in (ReplayStatus.SUCCESS, ReplayStatus.BUSINESS_OUTCOME) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
