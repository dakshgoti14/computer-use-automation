"""FastAPI application entrypoint for the integration layer's own API.

Run with:  uvicorn app.main:app --port 8000
(or:       make run-api)

This process is separate from the demo application (demo_app/app.py, port
8001 by default) - one is the reusable integration layer, the other is the
target surface it automates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from app.api.demo_page import demo_page
from app.api.rate_limit import RateLimiter
from app.api.routes import router
from app.api.run_store import RunStore
from app.artifacts.store import ArtifactStore
from app.config import Settings, get_settings
from app.escalation.intervention import InterventionManager
from app.escalation.session_control import SessionRegistry
from app.observability.logger import configure_logging


@dataclass
class IntegrationState:
    settings: Settings
    session_registry: SessionRegistry
    intervention_manager: InterventionManager
    artifact_store: ArtifactStore
    run_store: RunStore
    replay_rate_limiter: RateLimiter


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Computer-Use Automation Integration Layer",
        description=(
            "Reusable backend integration layer for AI agents operating "
            "applications without reliable APIs: LLM-driven discovery, "
            "structured capability artifacts, and deterministic replay."
        ),
        version="0.1.0",
    )

    session_registry = SessionRegistry()
    app.state.integration = IntegrationState(
        settings=settings,
        session_registry=session_registry,
        intervention_manager=InterventionManager(session_registry, evidence_root=settings.evidence_dir),
        artifact_store=ArtifactStore(settings.capabilities_dir),
        run_store=RunStore(Path(settings.evidence_dir) / "runs.sqlite3"),
        replay_rate_limiter=RateLimiter(
            max_requests=settings.public_demo_rate_limit_per_window,
            window_seconds=settings.public_demo_rate_limit_window_seconds,
        ),
    )

    app.include_router(router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    if settings.public_demo_mode:
        @app.get("/demo")
        async def demo():  # noqa: ANN202 - HTMLResponse, kept local to avoid an unused import path when disabled
            return demo_page()

        @app.get("/")
        async def root_redirect():
            from fastapi.responses import RedirectResponse

            return RedirectResponse(url="/demo")

    return app


app = create_app()
