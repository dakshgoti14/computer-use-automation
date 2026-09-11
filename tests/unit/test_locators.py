import pytest
from pydantic import ValidationError

from app.browser.locators import LocatorStrategyKind, LocatorTarget


def test_role_locator_requires_role_field():
    with pytest.raises(ValidationError):
        LocatorTarget(strategy=LocatorStrategyKind.ROLE)


def test_role_locator_valid():
    target = LocatorTarget(strategy=LocatorStrategyKind.ROLE, role="button", name="Search")
    assert target.describe() == "role=button name='Search'"


def test_css_locator_requires_css_field():
    with pytest.raises(ValidationError):
        LocatorTarget(strategy=LocatorStrategyKind.CSS)


def test_coordinate_locator_requires_xy():
    with pytest.raises(ValidationError):
        LocatorTarget(strategy=LocatorStrategyKind.COORDINATE, x=10.0)


def test_ordered_chain_includes_fallbacks():
    fallback = LocatorTarget(strategy=LocatorStrategyKind.CSS, css="#search-btn")
    primary = LocatorTarget(
        strategy=LocatorStrategyKind.ROLE, role="button", name="Search", fallbacks=[fallback]
    )
    chain = primary.ordered_chain()
    assert chain == [primary, fallback]


def test_locator_target_serializes_round_trip():
    target = LocatorTarget(strategy=LocatorStrategyKind.TEST_ID, test_id="member-search-input")
    payload = target.model_dump_json()
    restored = LocatorTarget.model_validate_json(payload)
    assert restored == target
