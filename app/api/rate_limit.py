"""A deliberately tiny in-memory per-client rate limiter.

Exists for exactly one reason: the public demo deployment runs a real
headless Chromium per replay request inside a resource-constrained
container. Nothing here needs a distributed store - the demo runs as a
single process, and this is scoped to protecting that one process from
being knocked over by repeated clicks, not to being a general-purpose
API gateway. If this system were ever deployed multi-instance, this would
need to move to a shared store (Redis, etc.) - noted rather than built,
per the assignment's guidance not to build infrastructure nobody asked for.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock


class RateLimiter:
    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        with self._lock:
            recent = [t for t in self._hits[key] if t > cutoff]
            if len(recent) >= self._max_requests:
                self._hits[key] = recent
                return False
            recent.append(now)
            self._hits[key] = recent
            return True
