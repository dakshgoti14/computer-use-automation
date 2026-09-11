"""Request/response contracts for the integration API.

Kept intentionally thin: these mostly wrap the domain models in
app.artifacts.schema / app.replay.result / app.agent.loop so the API layer
does not duplicate business logic, only (de)serialization.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.artifacts.schema import OutputSpec, ParameterSpec


class DiscoverRequest(BaseModel):
    goal: str
    capability_id: str
    description: str
    start_url: str
    inputs: list[ParameterSpec] = Field(default_factory=list)
    outputs: list[OutputSpec] = Field(default_factory=list)
    param_values: dict[str, str] = Field(default_factory=dict)
    allowed_domains: list[str] = Field(default_factory=list)
    max_steps: int = 20


class DiscoverResponse(BaseModel):
    run_id: str
    status: str
    message: str
    capability_id: str | None = None
    evidence_ref: str | None = None
    steps_taken: int


class ReplayRequest(BaseModel):
    params: dict[str, str] = Field(default_factory=dict)
    locator_profile_id: str | None = None
    start_url_override: str | None = None


class SessionSummary(BaseModel):
    session_id: str
    owner: str
    surface_kind: str
    created_at: str
    updated_at: str
    run_id: str | None = None


class EscalateRequest(BaseModel):
    reason: str
    run_id: str | None = None
    context: dict[str, str] = Field(default_factory=dict)


class TakeControlRequest(BaseModel):
    intervention_id: str
    operator_notes: str | None = None


class ResumeRequest(BaseModel):
    intervention_id: str


class RunRecord(BaseModel):
    run_id: str
    kind: str  # "discovery" | "replay"
    status: str
    capability_id: str | None = None
    message: str
    created_at: str
    evidence_ref: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
