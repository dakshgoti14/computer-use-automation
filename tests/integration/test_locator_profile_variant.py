"""Heterogeneity / multi-tenant demonstration: the SAME capability_id, with
a named locator_profile override, resolves correctly against a structurally
different UI variant of the member-detail page (no data-testid, different
labels) without duplicating the capability or its steps.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.artifacts.schema import ParamType
from app.browser.playwright_surface import PlaywrightSurface
from app.replay.executor import _resolve_locator_params
from app.replay.result import parse_typed_output
from tests.conftest import build_gold_artifact

pytestmark = pytest.mark.asyncio


async def test_variant_b_extracted_via_locator_profile_override(demo_app_base_url):
    """Focused demonstration (see REPORT.md "Cuts"): rather than extending
    the artifact schema so a locator_profile can also redirect navigation
    (Variant B is reached in this demo app via a query parameter, whereas a
    real multi-tenant deployment would simply be a different base URL per
    tenant), this test drives the surface directly to Variant B's page and
    resolves the SAME artifact's per-profile locator override against it -
    proving the override mechanism itself works against a genuinely
    different DOM shape.
    """

    artifact = build_gold_artifact(demo_app_base_url)
    profile = artifact.locator_profile("variant_b")
    assert profile is not None
    override_target = profile.step_target_overrides["step-06"]

    surface = PlaywrightSurface(headless=True)
    try:
        await surface.start_session(f"{demo_app_base_url}/login")
        from app.browser.locators import LocatorStrategyKind, LocatorTarget

        await surface.click(LocatorTarget(strategy=LocatorStrategyKind.ROLE, role="button", name="Sign In"))
        await surface.navigate(f"{demo_app_base_url}/members/12345?variant=b")

        resolved = _resolve_locator_params(override_target, {"member_id": "12345"})
        raw_value = await surface.extract(resolved)
    finally:
        await surface.close()

    typed = parse_typed_output(raw_value, ParamType.MONEY, output_name="savings_balance")
    assert typed.amount == Decimal("4231.55")

    # Confirm the DEFAULT (Variant A) locator would NOT have worked here -
    # this is genuinely a different DOM, not an accidental coincidence.
    default_target = next(s for s in artifact.steps if s.step_id == "step-06").target
    assert default_target.test_id != override_target.css
