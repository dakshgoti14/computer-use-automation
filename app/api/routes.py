"""Minimal, typed FastAPI surface over the discovery/replay/escalation engines.

Deliberately no auth/user infrastructure (per the assignment: this is a
take-home, not a production banking service) - endpoint contracts are still
fully typed via Pydantic request/response models.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from app.agent.loop import DiscoveryEngine
from app.agent.planner import Planner
from app.api.schemas import (
    DiscoverRequest,
    DiscoverResponse,
    EscalateRequest,
    ReplayRequest,
    ResumeRequest,
    RunRecord,
    SessionSummary,
    TakeControlRequest,
)
from app.browser.playwright_surface import PlaywrightSurface
from app.errors import AutomationError
from app.observability.evidence import EvidenceWriter
from app.providers import create_llm_provider
from app.replay.executor import ReplayEngine
from app.replay.result import ReplayResult
from app.safety.policy import SafetyPolicy

router = APIRouter()


def _state(request: Request):
    return request.app.state.integration


def _now() -> str:
    return datetime.now(UTC).isoformat()


@router.post("/runs/discover", response_model=DiscoverResponse)
async def discover(request: Request, body: DiscoverRequest) -> DiscoverResponse:
    state = _state(request)
    if state.settings.public_demo_mode:
        # A public endpoint that spends a real LLM budget per click is not
        # something to expose, independent of whether a key happens to be
        # configured in this environment - see app/config.py.
        raise HTTPException(
            status_code=403,
            detail="Live discovery is disabled in this public demo (it would spend a "
            "real LLM budget per click). See evidence/discovery/ in the repository "
            "for the genuine discovery run's transcript and screenshots, or run "
            "`make discover` locally with your own GEMINI_API_KEY.",
        )
    try:
        provider = create_llm_provider(state.settings)
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc

    allowed_domains = tuple(body.allowed_domains) or (state.settings.demo_app_host,)
    surface = PlaywrightSurface(headless=state.settings.headless_browser)
    run_id = str(uuid.uuid4())
    evidence = EvidenceWriter(evidence_root=state.settings.evidence_dir, run_kind="discovery", run_id=run_id)

    engine = DiscoveryEngine(
        surface=surface,
        planner=Planner(provider),
        safety_policy=SafetyPolicy(allowed_domains=allowed_domains),
        evidence=evidence,
        max_steps=body.max_steps,
    )

    result = await engine.run(
        goal=body.goal,
        start_url=body.start_url,
        capability_id=body.capability_id,
        description=body.description,
        inputs=body.inputs,
        outputs=body.outputs,
        param_values=body.param_values,
        allowed_domains=allowed_domains,
    )

    state.session_registry.register(surface, run_id=run_id)

    if result.status.value == "escalated":
        # Keep the session alive for handoff - do not close the surface.
        state.intervention_manager.request_escalation(
            session_id=surface.session.session_id, reason=result.escalation_reason or result.message,
            run_id=run_id, context=result.escalation_context,
        )
    else:
        if result.artifact is not None:
            state.artifact_store.save(result.artifact)
        await surface.close()
        state.session_registry.close(surface.session.session_id)

    state.run_store.save(RunRecord(
        run_id=run_id, kind="discovery", status=result.status.value,
        capability_id=body.capability_id if result.artifact else None,
        message=result.message, created_at=_now(), evidence_ref=result.evidence_ref,
    ))

    return DiscoverResponse(
        run_id=run_id, status=result.status.value, message=result.message,
        capability_id=body.capability_id if result.artifact else None,
        evidence_ref=result.evidence_ref, steps_taken=result.steps_taken,
    )


@router.post("/capabilities/{capability_id}/replay", response_model=ReplayResult)
async def replay_capability(request: Request, capability_id: str, body: ReplayRequest) -> ReplayResult:
    state = _state(request)

    if state.settings.public_demo_mode:
        if capability_id not in state.settings.public_demo_allowed_capabilities:
            raise HTTPException(
                status_code=403,
                detail=f"Capability {capability_id!r} is not replayable in this public demo.",
            )
        client_key = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else "unknown"
        )
        if not state.replay_rate_limiter.allow(client_key):
            raise HTTPException(
                status_code=429,
                detail="Rate limit reached for this public demo - each real replay spins "
                "up a real browser in a small shared container. Please wait a few "
                "minutes, or clone the repository and run `make replay` locally.",
            )

    try:
        artifact = state.artifact_store.load(capability_id)
    except AutomationError as exc:
        raise HTTPException(status_code=404, detail=exc.to_dict()) from exc

    if body.start_url_override:
        artifact = artifact.model_copy(update={"start_url_template": body.start_url_override})

    run_id = str(uuid.uuid4())
    evidence = EvidenceWriter(evidence_root=state.settings.evidence_dir, run_kind="replay", run_id=run_id)
    surface = PlaywrightSurface(headless=state.settings.headless_browser)
    engine = ReplayEngine(
        surface,
        safety_policy=SafetyPolicy(allowed_domains=artifact.safety.allowed_domains),
        evidence=evidence,
    )

    try:
        result = await engine.run(
            artifact, body.params, run_id=run_id, locator_profile_id=body.locator_profile_id
        )
    finally:
        await surface.close()

    state.run_store.save(RunRecord(
        run_id=run_id, kind="replay", status=result.status.value, capability_id=capability_id,
        message=result.message, created_at=_now(), evidence_ref=result.evidence_ref,
    ))
    return result


@router.get("/runs/{run_id}", response_model=RunRecord)
async def get_run(request: Request, run_id: str) -> RunRecord:
    record = _state(request).run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id!r}")
    return record


@router.get("/runs/{run_id}/events")
async def get_run_events(request: Request, run_id: str) -> list[dict]:
    record = _state(request).run_store.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id!r}")
    if not record.evidence_ref:
        return []
    from pathlib import Path

    events_path = Path(record.evidence_ref) / "run.jsonl"
    if not events_path.exists():
        return []
    import json

    return [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]


@router.get("/capabilities")
async def list_capabilities(request: Request) -> list[str]:
    return _state(request).artifact_store.list_capability_ids()


@router.get("/sessions/{session_id}", response_model=SessionSummary)
async def get_session(request: Request, session_id: str) -> SessionSummary:
    state = _state(request)
    try:
        managed = state.session_registry.get(session_id)
    except AutomationError as exc:
        raise HTTPException(status_code=404, detail=exc.to_dict()) from exc
    return SessionSummary(
        session_id=managed.session_id, owner=managed.owner.value,
        surface_kind=managed.surface.session.surface_kind.value,
        created_at=managed.created_at, updated_at=managed.updated_at, run_id=managed.run_id,
    )


@router.post("/sessions/{session_id}/escalate")
async def escalate_session(request: Request, session_id: str, body: EscalateRequest) -> dict:
    state = _state(request)
    try:
        intervention = state.intervention_manager.request_escalation(
            session_id=session_id, reason=body.reason, run_id=body.run_id, context=body.context,
        )
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc
    return intervention.model_dump()


@router.post("/sessions/{session_id}/take-control")
async def take_control(request: Request, session_id: str, body: TakeControlRequest) -> dict:
    state = _state(request)
    try:
        intervention = state.intervention_manager.take_control(
            body.intervention_id, operator_notes=body.operator_notes
        )
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc
    if intervention.session_id != session_id:
        raise HTTPException(status_code=400, detail="intervention does not belong to this session")
    return intervention.model_dump()


@router.post("/sessions/{session_id}/resume")
async def resume_session(request: Request, session_id: str, body: ResumeRequest) -> dict:
    state = _state(request)
    try:
        intervention = state.intervention_manager.request_resume(body.intervention_id)
        intervention = state.intervention_manager.complete_resume(body.intervention_id)
    except AutomationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc
    if intervention.session_id != session_id:
        raise HTTPException(status_code=400, detail="intervention does not belong to this session")
    return intervention.model_dump()
