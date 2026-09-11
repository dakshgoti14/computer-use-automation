"""Logical locator strategies.

This is the piece that makes capability artifacts reusable and portable
across surfaces/vendors: a step never stores a raw Playwright locator or a
brittle generated CSS selector. It stores *intent* - "the button whose
accessible name is Search" - ranked by a priority order from most to least
stable. Replay resolves this into whatever the concrete surface needs.

Priority order (most to least preferred):
    1. role + accessible name   (ARIA role/name - survives markup churn)
    2. label                    (form label text)
    3. test_id                  (stable data-testid / app attribute)
    4. text                     (stable visible text relationship)
    5. css                      (CSS selector - only when nothing semantic exists)
    6. xpath                    (last resort structural targeting)
    7. coordinate                (explicit last resort - fragile, logged loudly)
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class LocatorStrategyKind(str, Enum):
    ROLE = "role"
    LABEL = "label"
    TEST_ID = "test_id"
    TEXT = "text"
    CSS = "css"
    XPATH = "xpath"
    COORDINATE = "coordinate"


#: Stability ranking used to sort fallback chains and to flag risky artifacts.
STRATEGY_STABILITY_RANK: dict[LocatorStrategyKind, int] = {
    LocatorStrategyKind.ROLE: 0,
    LocatorStrategyKind.LABEL: 1,
    LocatorStrategyKind.TEST_ID: 2,
    LocatorStrategyKind.TEXT: 3,
    LocatorStrategyKind.CSS: 4,
    LocatorStrategyKind.XPATH: 5,
    LocatorStrategyKind.COORDINATE: 6,
}


#: Required field(s) per strategy, shared by every locator-shaped model
#: (including the LLM-facing schema in app.agent.models, which cannot use a
#: recursive ``fallbacks`` field because structured-output schemas forbid
#: recursion).
REQUIRED_FIELDS_BY_STRATEGY: dict[LocatorStrategyKind, tuple[str, ...]] = {
    LocatorStrategyKind.ROLE: ("role",),
    LocatorStrategyKind.LABEL: ("label",),
    LocatorStrategyKind.TEST_ID: ("test_id",),
    LocatorStrategyKind.TEXT: ("text",),
    LocatorStrategyKind.CSS: ("css",),
    LocatorStrategyKind.XPATH: ("xpath",),
    LocatorStrategyKind.COORDINATE: ("x", "y"),
}


class LocatorTarget(BaseModel):
    """A single logical locator, optionally with ordered fallbacks.

    Only the fields relevant to ``strategy`` need to be populated; the
    validator enforces that the required field for the chosen strategy is
    present so malformed artifacts fail fast rather than at replay time.
    """

    strategy: LocatorStrategyKind
    role: str | None = None
    name: str | None = None  # accessible name, used with ROLE
    label: str | None = None
    test_id: str | None = None
    text: str | None = None
    css: str | None = None
    xpath: str | None = None
    x: float | None = None
    y: float | None = None
    nth: int = Field(default=0, description="Index when a strategy matches multiple elements")
    fallbacks: list[LocatorTarget] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_required_fields(self) -> LocatorTarget:
        for field_name in REQUIRED_FIELDS_BY_STRATEGY[self.strategy]:
            if getattr(self, field_name) in (None, ""):
                raise ValueError(
                    f"strategy={self.strategy} requires field '{field_name}' to be set"
                )
        return self

    def describe(self) -> str:
        if self.strategy == LocatorStrategyKind.ROLE:
            return f"role={self.role} name={self.name!r}"
        if self.strategy == LocatorStrategyKind.LABEL:
            return f"label={self.label!r}"
        if self.strategy == LocatorStrategyKind.TEST_ID:
            return f"test_id={self.test_id!r}"
        if self.strategy == LocatorStrategyKind.TEXT:
            return f"text={self.text!r}"
        if self.strategy == LocatorStrategyKind.CSS:
            return f"css={self.css!r}"
        if self.strategy == LocatorStrategyKind.XPATH:
            return f"xpath={self.xpath!r}"
        return f"coordinate=({self.x}, {self.y})"

    def ordered_chain(self) -> list[LocatorTarget]:
        """This locator followed by its fallbacks, in the order to attempt."""

        return [self, *self.fallbacks]
