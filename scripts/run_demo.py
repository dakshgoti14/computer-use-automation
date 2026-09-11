#!/usr/bin/env python
"""Run the local demo banking back-office application in the foreground.

    python scripts/run_demo.py

Then open http://127.0.0.1:8001/login in a browser, or point
scripts/discover_capability.py / scripts/replay_capability.py at it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "demo_app.app:app", host=settings.demo_app_host, port=settings.demo_app_port, reload=False
    )


if __name__ == "__main__":
    main()
