#!/usr/bin/env python
"""Replay stability benchmark: run a capability N times and report real results.

    python scripts/benchmark_replay.py \\
        --capability capabilities/member_savings_lookup.json \\
        --member-id 12345 \\
        --runs 10

Every number printed comes from an actual executed run - nothing here is
fabricated. Results are also saved as evidence under evidence/replay/benchmark/.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.artifacts.store import ArtifactStore  # noqa: E402
from app.browser.playwright_surface import PlaywrightSurface  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.observability.evidence import EvidenceWriter  # noqa: E402
from app.replay.executor import ReplayEngine  # noqa: E402
from app.safety.policy import SafetyPolicy  # noqa: E402
from scripts._common import ensure_demo_app_running  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--member-id", default="12345")
    parser.add_argument("--runs", type=int, default=10)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    store = ArtifactStore(settings.capabilities_dir)
    artifact = store.load_path(Path(args.capability))
    demo_proc = ensure_demo_app_running(settings.demo_app_base_url)

    benchmark_id = uuid.uuid4().hex[:12]
    durations: list[float] = []
    statuses: list[str] = []
    checkpoint_failures = 0

    print(f"[benchmark] capability={artifact.capability_id} runs={args.runs} member_id={args.member_id}")

    try:
        for i in range(1, args.runs + 1):
            run_id = f"{benchmark_id}-{i:03d}"
            evidence = EvidenceWriter(
                evidence_root=settings.evidence_dir, run_kind="replay/benchmark", run_id=run_id
            )
            surface = PlaywrightSurface(headless=settings.headless_browser)
            engine = ReplayEngine(
                surface,
                safety_policy=SafetyPolicy(allowed_domains=artifact.safety.allowed_domains),
                evidence=evidence,
            )
            start = time.monotonic()
            try:
                result = await engine.run(artifact, {"member_id": args.member_id}, run_id=run_id)
            finally:
                await surface.close()
            elapsed = (time.monotonic() - start) * 1000

            durations.append(elapsed)
            statuses.append(result.status.value)
            checkpoint_failures += sum(
                1 for step in result.steps for c in step.checkpoints if not c.passed
            )
            print(f"  run {i:>2}/{args.runs}: status={result.status.value:<18} "
                  f"duration_ms={elapsed:.0f} retries={result.total_retries}")
    finally:
        if demo_proc:
            demo_proc.terminate()

    total = len(statuses)
    successful = statuses.count("success")
    business_outcomes = statuses.count("business_outcome")
    failed = total - successful - business_outcomes
    failure_rate = failed / total if total else 0.0

    summary = {
        "benchmark_id": benchmark_id,
        "capability_id": artifact.capability_id,
        "member_id": args.member_id,
        "total_runs": total,
        "successful_runs": successful,
        "business_outcome_runs": business_outcomes,
        "failed_runs": failed,
        "failure_rate": round(failure_rate, 4),
        "checkpoint_failures": checkpoint_failures,
        "avg_duration_ms": round(statistics.mean(durations), 1) if durations else 0.0,
        "min_duration_ms": round(min(durations), 1) if durations else 0.0,
        "max_duration_ms": round(max(durations), 1) if durations else 0.0,
    }

    print("\n[benchmark] summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    import json

    out_dir = Path(settings.evidence_dir) / "replay" / "benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{benchmark_id}-summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\n[benchmark] summary saved to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
