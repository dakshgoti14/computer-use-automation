"""Filesystem persistence for capability artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from app.artifacts.schema import CapabilityArtifact
from app.artifacts.validator import validate_artifact
from app.errors import ErrorCode, HardFailureError


class ArtifactStore:
    def __init__(self, capabilities_dir: Path) -> None:
        self.capabilities_dir = capabilities_dir
        self.capabilities_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, capability_id: str) -> Path:
        safe_id = capability_id.replace("/", "_")
        return self.capabilities_dir / f"{safe_id}.json"

    def save(self, artifact: CapabilityArtifact) -> Path:
        validate_artifact(artifact)
        path = self._path_for(artifact.capability_id)
        path.write_text(artifact.model_dump_json(indent=2))
        return path

    def load(self, capability_id: str) -> CapabilityArtifact:
        path = self._path_for(capability_id)
        return self.load_path(path)

    def load_path(self, path: Path) -> CapabilityArtifact:
        if not path.exists():
            raise HardFailureError(
                ErrorCode.ARTIFACT_INVALID, f"Capability artifact not found at {path}"
            )
        try:
            payload = json.loads(path.read_text())
            artifact = CapabilityArtifact.model_validate(payload)
        except HardFailureError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HardFailureError(
                ErrorCode.ARTIFACT_INVALID,
                f"Capability artifact at {path} is not valid JSON matching the schema: {exc}",
            ) from exc
        validate_artifact(artifact)
        return artifact

    def list_capability_ids(self) -> list[str]:
        return sorted(p.stem for p in self.capabilities_dir.glob("*.json"))
