"""Evidence capture: structured JSONL events, screenshots, and snapshots.

Layout (see README "Evidence directory"):

    evidence/<run_kind>/<run_id>/
        run.jsonl
        screenshots/step-XX.png
        observations/step-XX.json
        artifact.json          (discovery runs only)

``run_kind`` and ``run_id`` are sanitized before touching the filesystem so
a malicious/garbled id can never escape the evidence root (path traversal
is explicitly called out in the assignment's security checklist).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.observability.events import Event
from app.safety.redaction import redact_dict

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9_.\-]")


def _sanitize(segment: str) -> str:
    cleaned = _SAFE_SEGMENT.sub("_", segment)
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError(f"Refusing unsafe evidence path segment: {segment!r}")
    return cleaned


def _sanitize_path(path_like: str) -> Path:
    """Sanitize a ``/``-separated run_kind into nested directories.

    Each segment is sanitized independently (no ``..``, no traversal
    characters survive), so ``"errors/member_not_found"`` safely becomes
    ``evidence/errors/member_not_found/`` rather than a single mangled
    directory name - this is what lets the evidence tree match the layout
    documented in README "Evidence directory".
    """

    parts = [p for p in path_like.split("/") if p]
    if not parts:
        raise ValueError(f"Refusing empty evidence path: {path_like!r}")
    result = Path(_sanitize(parts[0]))
    for part in parts[1:]:
        result = result / _sanitize(part)
    return result


class EvidenceWriter:
    """Writes evidence for a single run under ``evidence/<run_kind>/<run_id>/``.

    ``run_kind`` may itself be a ``/``-separated path (e.g.
    ``"errors/member_not_found"``) to group related runs into subdirectories.
    """

    def __init__(self, *, evidence_root: Path, run_kind: str, run_id: str) -> None:
        self.run_dir = evidence_root / _sanitize_path(run_kind) / _sanitize(run_id)
        self.screenshots_dir = self.run_dir / "screenshots"
        self.observations_dir = self.run_dir / "observations"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.observations_dir.mkdir(parents=True, exist_ok=True)
        self._events_path = self.run_dir / "run.jsonl"

    def record_event(self, event: Event) -> None:
        safe_payload = redact_dict(event.model_dump())
        with self._events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(safe_payload, default=str) + "\n")

    def screenshot_path(self, label: str) -> str:
        return str(self.screenshots_dir / f"{_sanitize(label)}.png")

    def save_observation(self, label: str, observation: dict[str, Any]) -> str:
        path = self.observations_dir / f"{_sanitize(label)}.json"
        path.write_text(json.dumps(redact_dict(observation), indent=2, default=str))
        return str(path)

    def save_json(self, filename: str, payload: dict[str, Any]) -> str:
        path = self.run_dir / _sanitize(filename)
        path.write_text(json.dumps(redact_dict(payload), indent=2, default=str))
        return str(path)

    def read_events(self) -> list[dict[str, Any]]:
        if not self._events_path.exists():
            return []
        lines = self._events_path.read_text().splitlines()
        return [json.loads(line) for line in lines if line.strip()]
