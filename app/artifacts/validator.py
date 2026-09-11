"""Structural validation for capability artifacts, run before every replay.

This is separate from the pydantic field validators in schema.py because it
checks *cross-field* invariants (do checkpoint references resolve? do
template parameter references match declared inputs?) that need the whole
artifact in view.
"""

from __future__ import annotations

from app.artifacts.schema import CapabilityArtifact, extract_param_refs
from app.errors import ErrorCode, HardFailureError

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}


def validate_artifact(artifact: CapabilityArtifact) -> None:
    """Raise :class:`HardFailureError` (ARTIFACT_INVALID) on any structural defect."""

    problems: list[str] = []

    if artifact.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        problems.append(
            f"Unsupported schema_version {artifact.schema_version!r}; "
            f"supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    if not artifact.steps:
        problems.append("Artifact has zero steps")

    if not artifact.safety.allowed_domains:
        problems.append("safety.allowed_domains must not be empty")

    known_checkpoint_ids = {cp.checkpoint_id for cp in artifact.checkpoints}
    input_names = artifact.input_names()

    for step in artifact.steps:
        for cp_id in step.checkpoint_ids:
            if cp_id not in known_checkpoint_ids:
                problems.append(f"step {step.step_id!r} references unknown checkpoint {cp_id!r}")

        for template_field, template in (
            ("value_template", step.value_template),
            ("url_template", step.url_template),
        ):
            if not template:
                continue
            unknown = extract_param_refs(template) - input_names
            if unknown:
                problems.append(
                    f"step {step.step_id!r} {template_field} references undeclared "
                    f"parameter(s) {sorted(unknown)}"
                )

    unknown_start = extract_param_refs(artifact.start_url_template) - input_names
    if unknown_start:
        problems.append(
            f"start_url_template references undeclared parameter(s) {sorted(unknown_start)}"
        )

    declared_output_names = {o.name for o in artifact.outputs}
    produced_output_names = {s.output_name for s in artifact.steps if s.output_name}
    missing_producers = declared_output_names - produced_output_names
    if missing_producers:
        problems.append(
            f"outputs {sorted(missing_producers)} are declared but no step extracts them"
        )

    for profile in artifact.locator_profiles:
        step_ids = {s.step_id for s in artifact.steps}
        unknown_steps = set(profile.step_target_overrides) - step_ids
        if unknown_steps:
            problems.append(
                f"locator_profile {profile.profile_id!r} overrides unknown "
                f"step(s) {sorted(unknown_steps)}"
            )

    if problems:
        raise HardFailureError(
            ErrorCode.ARTIFACT_INVALID,
            f"Capability artifact {artifact.capability_id!r} v{artifact.version} failed "
            f"validation with {len(problems)} problem(s).",
            context={"problems": problems},
        )
