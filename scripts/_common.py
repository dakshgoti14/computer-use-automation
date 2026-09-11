"""Shared helpers for the CLI scripts (not part of the reusable library)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent


def ensure_demo_app_running(base_url: str, *, timeout_s: float = 15.0) -> subprocess.Popen | None:
    """Start the demo app as a subprocess if it isn't already reachable.

    Returns the ``Popen`` handle if THIS call started it (caller is
    responsible for terminating it), or ``None`` if it was already running.
    """

    try:
        httpx.get(f"{base_url}/login", timeout=1.0)
        print(f"[bootstrap] demo app already running at {base_url}")
        return None
    except httpx.HTTPError:
        pass

    print(f"[bootstrap] starting demo app at {base_url} ...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "demo_app.app"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{base_url}/login", timeout=1.0)
            print("[bootstrap] demo app is ready")
            return proc
        except httpx.HTTPError:
            time.sleep(0.3)
    proc.terminate()
    raise RuntimeError(f"demo app did not become ready at {base_url} within {timeout_s}s")


def print_json(payload: object) -> None:
    import json

    def _default(o: object) -> object:
        if hasattr(o, "model_dump"):
            return o.model_dump(mode="json")
        return str(o)

    print(json.dumps(payload, indent=2, default=_default))
