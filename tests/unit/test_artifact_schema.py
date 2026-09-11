import pytest
from pydantic import ValidationError

from app.artifacts.schema import (
    CapabilityArtifact,
    CapabilityStep,
    Checkpoint,
    CheckpointKind,
    OutputSpec,
    ParameterSpec,
    ParamType,
    SafetySpec,
    extract_param_refs,
    resolve_template,
)
from app.artifacts.validator import validate_artifact
from app.browser.locators import LocatorStrategyKind, LocatorTarget
from app.errors import HardFailureError


def _minimal_artifact(**overrides) -> CapabilityArtifact:
    defaults = dict(
        capability_id="test_capability",
        version=1,
        description="A minimal test capability",
        start_url_template="http://example.test/start",
        inputs=[ParameterSpec(name="member_id", type=ParamType.STRING)],
        outputs=[OutputSpec(name="balance", type=ParamType.MONEY)],
        steps=[
            CapabilityStep(
                step_id="s1", description="fill", action="fill",
                target=LocatorTarget(strategy=LocatorStrategyKind.TEST_ID, test_id="x"),
                value_template="${member_id}",
            ),
            CapabilityStep(
                step_id="s2", description="extract", action="extract",
                target=LocatorTarget(strategy=LocatorStrategyKind.TEST_ID, test_id="y"),
                output_name="balance",
            ),
        ],
        safety=SafetySpec(allowed_domains=("example.test",)),
    )
    defaults.update(overrides)
    return CapabilityArtifact(**defaults)


def test_resolve_template_substitutes_known_params():
    assert resolve_template("id=${member_id}", {"member_id": "12345"}) == "id=12345"


def test_resolve_template_fails_closed_on_unknown_param():
    with pytest.raises(KeyError):
        resolve_template("id=${member_id}", {})


def test_extract_param_refs():
    assert extract_param_refs("${a} and ${b} and ${a}") == {"a", "b"}


def test_minimal_artifact_validates():
    artifact = _minimal_artifact()
    validate_artifact(artifact)  # must not raise


def test_step_referencing_unknown_checkpoint_fails_validation():
    artifact = _minimal_artifact()
    artifact.steps[0].checkpoint_ids = ["does-not-exist"]
    with pytest.raises(HardFailureError):
        validate_artifact(artifact)


def test_step_referencing_undeclared_parameter_fails_validation():
    artifact = _minimal_artifact()
    artifact.steps[0].value_template = "${undeclared_param}"
    with pytest.raises(HardFailureError):
        validate_artifact(artifact)


def test_output_with_no_producing_step_fails_validation():
    artifact = _minimal_artifact()
    artifact.outputs.append(OutputSpec(name="unused_output", type=ParamType.STRING))
    with pytest.raises(HardFailureError):
        validate_artifact(artifact)


def test_empty_allowed_domains_fails_validation():
    artifact = _minimal_artifact()
    artifact.safety.allowed_domains = ()
    with pytest.raises(HardFailureError):
        validate_artifact(artifact)


def test_fill_step_without_value_template_rejected_at_construction():
    with pytest.raises(ValidationError):
        CapabilityStep(
            step_id="bad", description="fill without value", action="fill",
            target=LocatorTarget(strategy=LocatorStrategyKind.TEST_ID, test_id="x"),
        )


def test_finish_action_rejected_as_capability_step():
    with pytest.raises(ValidationError):
        CapabilityStep(step_id="bad", description="finish", action="finish")


def test_checkpoint_requires_matching_fields():
    with pytest.raises(ValidationError):
        Checkpoint(checkpoint_id="c1", description="bad", kind=CheckpointKind.TEXT_CONTAINS)


def test_artifact_version_must_be_positive():
    with pytest.raises(ValidationError):
        _minimal_artifact(version=0)
