"""Playwright implementation of :class:`app.browser.surface.SurfaceAdapter`.

This is the only concrete surface implemented for this assessment. Nothing
outside this module (and its factory) imports Playwright - the agent loop
and replay engine talk exclusively to the ``SurfaceAdapter`` protocol.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from playwright.async_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    async_playwright,
)

from app.browser.locators import LocatorStrategyKind, LocatorTarget
from app.browser.observation import Observation
from app.browser.surface import SurfaceKind, SurfaceSessionState
from app.errors import ErrorCode, HardFailureError, RecoverableError

_EXTRACT_JS = (Path(__file__).parent / "_extract.js").read_text()

#: Default per-locator resolution timeout. Kept short and bounded - the
#: agent/replay retry policy handles waiting across multiple attempts, this
#: is not the place for open-ended waits.
_LOCATOR_TIMEOUT_MS = 3000


def _build_playwright_locator(page: Page, target: LocatorTarget) -> Locator:
    """Translate one logical :class:`LocatorTarget` into a Playwright locator.

    Does not attempt fallbacks - callers use :func:`resolve_locator` for the
    full fallback chain with clean error classification.
    """

    # LocatorTarget's own validator (app.browser.locators) already guarantees
    # the field required by each strategy is non-empty; the `is not None`
    # asserts below narrow that for the type checker. Our `role` is a plain
    # str (deliberately more permissive than Playwright's narrow AriaRole
    # Literal, since a hostile/legacy app may expose non-standard roles), so
    # that one call needs an explicit ignore for the Literal mismatch.
    if target.strategy == LocatorStrategyKind.ROLE:
        assert target.role is not None
        return page.get_by_role(target.role, name=target.name, exact=False).nth(target.nth)  # type: ignore[arg-type]
    if target.strategy == LocatorStrategyKind.LABEL:
        assert target.label is not None
        return page.get_by_label(target.label, exact=False).nth(target.nth)
    if target.strategy == LocatorStrategyKind.TEST_ID:
        assert target.test_id is not None
        return page.get_by_test_id(target.test_id).nth(target.nth)
    if target.strategy == LocatorStrategyKind.TEXT:
        assert target.text is not None
        return page.get_by_text(target.text, exact=False).nth(target.nth)
    if target.strategy == LocatorStrategyKind.CSS:
        assert target.css is not None
        return page.locator(target.css).nth(target.nth)
    if target.strategy == LocatorStrategyKind.XPATH:
        assert target.xpath is not None
        return page.locator(f"xpath={target.xpath}").nth(target.nth)
    raise HardFailureError(
        ErrorCode.UNSUPPORTED_ACTION,
        f"Locator strategy {target.strategy} cannot be resolved to a Playwright locator "
        "directly (coordinate targeting is handled separately).",
    )


async def resolve_locator(page: Page, target: LocatorTarget) -> Locator:
    """Resolve a locator, trying ``target`` then each fallback in order.

    Raises :class:`RecoverableError` (LOCATOR_TIMEOUT_TRANSIENT) if the
    *primary* strategy simply hasn't rendered yet, or
    :class:`HardFailureError` (LOCATOR_NOT_FOUND) once the entire chain is
    exhausted.
    """

    chain = target.ordered_chain()
    last_error: Exception | None = None
    for candidate in chain:
        if candidate.strategy == LocatorStrategyKind.COORDINATE:
            # Coordinate targeting has no Playwright Locator equivalent; it is
            # handled by the caller directly via page.mouse.
            continue
        try:
            locator = _build_playwright_locator(page, candidate)
            await locator.wait_for(state="visible", timeout=_LOCATOR_TIMEOUT_MS)
            return locator
        except Exception as exc:  # noqa: BLE001 - classified below
            last_error = exc
            continue

    # Every candidate failed. If this was the *only* attempt (no fallbacks)
    # treat it as potentially transient so the retry policy gets a shot.
    if len(chain) == 1:
        raise RecoverableError(
            ErrorCode.LOCATOR_TIMEOUT_TRANSIENT,
            f"Element not yet visible for locator {target.describe()}",
            context={"strategy": target.strategy.value, "detail": str(last_error)},
        )
    raise HardFailureError(
        ErrorCode.LOCATOR_NOT_FOUND,
        f"Exhausted {len(chain)} locator strategies, none resolved: "
        f"{[c.describe() for c in chain]}",
        context={"detail": str(last_error)},
    )


class PlaywrightSurface:
    """Concrete browser automation surface backed by Playwright (Chromium)."""

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.session = SurfaceSessionState(
            session_id=str(uuid.uuid4()), surface_kind=SurfaceKind.PLAYWRIGHT_WEB
        )

    @property
    def page(self) -> Page:
        if self._page is None:
            raise HardFailureError(
                ErrorCode.UNSUPPORTED_ACTION, "Surface session has not been started"
            )
        return self._page

    async def start_session(self, start_url: str) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        await self._page.goto(start_url, wait_until="domcontentloaded")

    async def observe(self) -> Observation:
        from app.browser.observation import MAX_INTERACTIVE_ELEMENTS, MAX_VISIBLE_TEXT_CHARS

        await self.page.wait_for_load_state("domcontentloaded")
        raw = await self.page.evaluate(
            _EXTRACT_JS, [MAX_INTERACTIVE_ELEMENTS, MAX_VISIBLE_TEXT_CHARS]
        )
        # Bound already enforced in JS; keep a Python-side ceiling too in
        # case the page mutates between the call and this check.
        raw["interactive_elements"] = raw["interactive_elements"][:MAX_INTERACTIVE_ELEMENTS]
        return Observation(**raw)

    async def click(self, target: LocatorTarget) -> None:
        if target.strategy == LocatorStrategyKind.COORDINATE:
            assert target.x is not None and target.y is not None
            await self.page.mouse.click(target.x, target.y)
            return
        locator = await resolve_locator(self.page, target)
        await locator.click(timeout=_LOCATOR_TIMEOUT_MS)

    async def fill(self, target: LocatorTarget, value: str) -> None:
        locator = await resolve_locator(self.page, target)
        await locator.fill(value, timeout=_LOCATOR_TIMEOUT_MS)

    async def select(self, target: LocatorTarget, value: str) -> None:
        locator = await resolve_locator(self.page, target)
        await locator.select_option(value, timeout=_LOCATOR_TIMEOUT_MS)

    async def extract(self, target: LocatorTarget) -> str:
        locator = await resolve_locator(self.page, target)
        text = await locator.text_content(timeout=_LOCATOR_TIMEOUT_MS)
        if text is None:
            text = await locator.input_value(timeout=_LOCATOR_TIMEOUT_MS)
        return (text or "").strip()

    async def wait_for(self, target: LocatorTarget, timeout_ms: int = 5000) -> bool:
        try:
            locator = _build_playwright_locator(self.page, target)
            await locator.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def navigate(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded")

    async def screenshot(self, evidence_path: str) -> str:
        path = Path(evidence_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(path))
        return str(path)

    async def current_url(self) -> str:
        return self.page.url

    async def close(self) -> None:
        if self.session.closed:
            return
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self.session.closed = True
