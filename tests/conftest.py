"""Shared test fixtures: a live demo-app server and a hand-built "gold"
capability artifact used to exercise the ReplayEngine.

Important integrity note: this gold artifact is a TEST FIXTURE, not the
genuine discovery output. The real ``capabilities/member_savings_lookup.json``
is produced only by an actual Gemini-driven run of
``scripts/discover_capability.py`` against this same demo app - see
README "Running genuine discovery". Hand-authoring a fixture here lets the
replay engine, checkpoints, safety policy, and error taxonomy be tested
deterministically and quickly, without depending on network access or an
API key, which is exactly what the assignment's testing section asks for.
"""

from __future__ import annotations

import threading
import time

import pytest
import uvicorn

from app.artifacts.schema import (
    CapabilityArtifact,
    CapabilityStep,
    Checkpoint,
    CheckpointKind,
    ErrorMappingRule,
    LocatorProfile,
    OutputSpec,
    ParameterSpec,
    ParamType,
    SafetySpec,
)
from app.browser.locators import LocatorStrategyKind, LocatorTarget
from app.errors import ErrorCode


@pytest.fixture(scope="session")
def demo_app_base_url():
    from demo_app.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=8099, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "demo app server failed to start"
    yield "http://127.0.0.1:8099"
    server.should_exit = True
    thread.join(timeout=5)


def build_gold_artifact(base_url: str) -> CapabilityArtifact:
    """The member-savings-lookup capability, hand-built to mirror exactly
    what a successful discovery run against this demo app produces."""

    steps = [
        CapabilityStep(
            step_id="step-01",
            description="Sign in to reach the authenticated back office",
            action="click",
            target=LocatorTarget(strategy=LocatorStrategyKind.ROLE, role="button", name="Sign In"),
            checkpoint_ids=["cp-step-01-url"],
        ),
        CapabilityStep(
            step_id="step-02",
            description="Navigate to member search",
            action="click",
            target=LocatorTarget(strategy=LocatorStrategyKind.ROLE, role="link", name="Search Members"),
            checkpoint_ids=["cp-step-02-url"],
        ),
        CapabilityStep(
            step_id="step-03",
            description="Enter the member id to search for",
            action="fill",
            target=LocatorTarget(strategy=LocatorStrategyKind.TEST_ID, test_id="member-search-input"),
            value_template="${member_id}",
            checkpoint_ids=["cp-step-03-target"],
        ),
        CapabilityStep(
            step_id="step-04",
            description="Submit the member search",
            action="click",
            target=LocatorTarget(strategy=LocatorStrategyKind.TEST_ID, test_id="member-search-submit"),
            checkpoint_ids=["cp-step-04-results"],
        ),
        CapabilityStep(
            step_id="step-05",
            description="Open the matched member's detail page",
            action="click",
            target=LocatorTarget(
                strategy=LocatorStrategyKind.TEST_ID, test_id="view-member-${member_id}"
            ),
            checkpoint_ids=["cp-step-05-url"],
        ),
        CapabilityStep(
            step_id="step-06",
            description="Read the member's current savings balance",
            action="extract",
            target=LocatorTarget(strategy=LocatorStrategyKind.TEST_ID, test_id="savings-balance"),
            output_name="savings_balance",
            checkpoint_ids=["cp-step-06-value"],
        ),
    ]

    checkpoints = [
        Checkpoint(
            checkpoint_id="cp-step-01-url", description="Landed on the dashboard after sign-in",
            kind=CheckpointKind.URL_MATCHES, url_pattern=r"/dashboard$",
        ),
        Checkpoint(
            checkpoint_id="cp-step-02-url", description="Landed on the member search page",
            kind=CheckpointKind.URL_MATCHES, url_pattern=r"/members/search$",
        ),
        Checkpoint(
            checkpoint_id="cp-step-03-target", description="Search input is present",
            kind=CheckpointKind.ELEMENT_VISIBLE,
            target=LocatorTarget(strategy=LocatorStrategyKind.TEST_ID, test_id="member-search-input"),
        ),
        Checkpoint(
            checkpoint_id="cp-step-04-results", description="Search results panel is visible",
            kind=CheckpointKind.ELEMENT_VISIBLE,
            target=LocatorTarget(strategy=LocatorStrategyKind.TEST_ID, test_id="view-member-${member_id}"),
        ),
        Checkpoint(
            checkpoint_id="cp-step-05-url", description="Landed on the member detail page",
            kind=CheckpointKind.URL_MATCHES, url_pattern=r"/members/[^/]+$",
        ),
        Checkpoint(
            checkpoint_id="cp-step-06-value", description="Extracted savings balance looks like money",
            kind=CheckpointKind.VALUE_MATCHES_PATTERN,
            value_pattern=r"^-?\$?\d{1,3}(,\d{3})*(\.\d{2})?$",
        ),
    ]

    error_mapping = [
        ErrorMappingRule(
            match_kind="banner_text_contains", match_value="no members found",
            error_code=ErrorCode.MEMBER_NOT_FOUND,
            message="The application reported that no matching member exists.",
        ),
        ErrorMappingRule(
            match_kind="banner_text_contains", match_value="session has expired",
            error_code=ErrorCode.SESSION_TIMEOUT,
            message="The application session expired and requires re-authentication.",
        ),
        ErrorMappingRule(
            match_kind="text_contains", match_value="unexpected error occurred",
            error_code=ErrorCode.UNEXPECTED_APPLICATION_ERROR,
            message="The application reported an unexpected internal error.",
        ),
    ]

    # Variant B locator profile: same capability_id, only the member-detail
    # extraction step's target changes, demonstrating heterogeneity/vendor
    # variance without duplicating the capability (see REPORT.md).
    locator_profiles = [
        LocatorProfile(
            profile_id="variant_b",
            description="Alternate member-detail UI with no data-testid on balances",
            step_target_overrides={
                # Variant B has no data-testid or role on the balance figure -
                # only a stable custom attribute (aria-label). Per the
                # locator priority order, CSS is used here deliberately as
                # the least-fragile strategy actually available, not as a
                # shortcut around a better one.
                "step-06": LocatorTarget(
                    strategy=LocatorStrategyKind.CSS,
                    css="[aria-label='Available Savings amount']",
                )
            },
        )
    ]

    return CapabilityArtifact(
        capability_id="member_savings_lookup",
        version=1,
        description="Look up a member and return their current savings balance.",
        start_url_template=f"{base_url}/login",
        inputs=[ParameterSpec(name="member_id", type=ParamType.STRING, required=True)],
        outputs=[OutputSpec(name="savings_balance", type=ParamType.MONEY)],
        preconditions=["User session must be authenticated against the target application."],
        steps=steps,
        checkpoints=checkpoints,
        error_mapping=error_mapping,
        safety=SafetySpec(allowed_domains=("127.0.0.1",)),
        locator_profiles=locator_profiles,
    )
