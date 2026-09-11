"""Structured event schema written to evidence JSONL files."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    OBSERVATION = "observation"
    AGENT_DECISION = "agent_decision"
    POLICY_DECISION = "policy_decision"
    ACTION_EXECUTED = "action_executed"
    CHECKPOINT_EVALUATED = "checkpoint_evaluated"
    RETRY_ATTEMPTED = "retry_attempted"
    ERROR = "error"
    ESCALATION_REQUESTED = "escalation_requested"
    HUMAN_CONTROL_TAKEN = "human_control_taken"
    AUTOMATION_RESUMED = "automation_resumed"
    ARTIFACT_CREATED = "artifact_created"


class Event(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    run_id: str
    session_id: str | None = None
    event_type: EventType
    step_id: str | None = None
    action: str | None = None
    target: str | None = None
    status: str | None = None
    duration_ms: float | None = None
    error_code: str | None = None
    evidence_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
