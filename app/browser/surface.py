"""The ``SurfaceAdapter`` protocol.

Neither the agent loop nor the replay engine import Playwright directly -
they depend only on this protocol. That is what lets a future
``LegacyWebSurface`` or ``DesktopSurface`` be dropped in without touching
agent/replay code (see REPORT.md, "Heterogeneity & multi-tenant").

A surface is intentionally *dumb*: it knows how to observe and act on a
concrete UI. It has no notion of goals, capabilities, or LLMs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from app.browser.locators import LocatorTarget
from app.browser.observation import Observation


class SurfaceKind(str, Enum):
    PLAYWRIGHT_WEB = "playwright_web"
    LEGACY_WEB = "legacy_web"  # future - not implemented
    DESKTOP = "desktop"  # future - not implemented


class SessionOwner(str, Enum):
    AUTOMATION = "automation"
    HUMAN = "human"


@dataclass
class SurfaceSessionState:
    """Session bookkeeping shared by every surface implementation."""

    session_id: str
    surface_kind: SurfaceKind
    owner: SessionOwner = SessionOwner.AUTOMATION
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_action_at: datetime | None = None
    closed: bool = False


@runtime_checkable
class SurfaceAdapter(Protocol):
    """Protocol every UI-automation surface must implement.

    Implementations: :class:`app.browser.playwright_surface.PlaywrightSurface`.
    Future (documented, not implemented): a legacy-web surface driven by
    plain HTTP + HTML parsing, and a desktop-automation surface.
    """

    session: SurfaceSessionState

    async def start_session(self, start_url: str) -> None:
        """Open the target application and navigate to ``start_url``."""
        ...

    async def observe(self) -> Observation:
        """Return a bounded, structured snapshot of the current page."""
        ...

    async def click(self, target: LocatorTarget) -> None: ...

    async def fill(self, target: LocatorTarget, value: str) -> None: ...

    async def select(self, target: LocatorTarget, value: str) -> None: ...

    async def extract(self, target: LocatorTarget) -> str:
        """Return the text/value content of the located element."""
        ...

    async def wait_for(self, target: LocatorTarget, timeout_ms: int = 5000) -> bool:
        """Wait until ``target`` is visible; return False on timeout (no raise)."""
        ...

    async def navigate(self, url: str) -> None:
        """Navigate directly to a URL. Callers must safety-check this first."""
        ...

    async def screenshot(self, evidence_path: str) -> str:
        """Persist a screenshot to ``evidence_path`` and return its ref."""
        ...

    async def current_url(self) -> str: ...

    async def close(self) -> None: ...
