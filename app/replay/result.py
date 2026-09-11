"""Typed replay results and output value representations.

Money is never a float. ``MoneyValue.amount`` is a :class:`decimal.Decimal`,
parsed strictly from the page text - a malformed or unparseable value never
silently becomes ``0`` or ``NaN``, it raises OUTPUT_CONVERSION_FAILED.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.artifacts.schema import ParamType
from app.errors import ErrorCode, HardFailureError
from app.replay.checkpoints import CheckpointResult

_MONEY_TEXT_PATTERN = re.compile(r"^-?\$?\s*(\d{1,3}(?:,\d{3})*|\d+)(\.\d{2})?$")


class MoneyValue(BaseModel):
    amount: Decimal
    currency: str = "USD"

    def __str__(self) -> str:
        return f"{self.currency} {self.amount:,.2f}"


def parse_typed_output(raw_text: str, param_type: ParamType, *, output_name: str) -> Any:
    """Convert raw extracted page text into a validated typed value.

    Raises :class:`HardFailureError` (OUTPUT_CONVERSION_FAILED) rather than
    returning a best-effort/garbage value when the text does not match the
    expected shape.
    """

    cleaned = raw_text.strip()

    if param_type == ParamType.MONEY:
        match = _MONEY_TEXT_PATTERN.match(cleaned)
        if not match:
            raise HardFailureError(
                ErrorCode.OUTPUT_CONVERSION_FAILED,
                f"Output '{output_name}' value {raw_text!r} does not look like a money amount",
                context={"raw_value": raw_text},
            )
        numeric = cleaned.replace("$", "").replace(",", "")
        try:
            amount = Decimal(numeric)
        except InvalidOperation as exc:
            raise HardFailureError(
                ErrorCode.OUTPUT_CONVERSION_FAILED,
                f"Output '{output_name}' value {raw_text!r} could not be parsed as Decimal",
            ) from exc
        return MoneyValue(amount=amount)

    if param_type == ParamType.NUMBER:
        try:
            return Decimal(cleaned)
        except InvalidOperation as exc:
            raise HardFailureError(
                ErrorCode.OUTPUT_CONVERSION_FAILED,
                f"Output '{output_name}' value {raw_text!r} is not a valid number",
            ) from exc

    if param_type == ParamType.BOOLEAN:
        if cleaned.lower() in {"true", "yes", "active"}:
            return True
        if cleaned.lower() in {"false", "no", "inactive"}:
            return False
        raise HardFailureError(
            ErrorCode.OUTPUT_CONVERSION_FAILED,
            f"Output '{output_name}' value {raw_text!r} is not a recognizable boolean",
        )

    if not cleaned:
        raise HardFailureError(
            ErrorCode.OUTPUT_CONVERSION_FAILED,
            f"Output '{output_name}' extracted an empty string",
        )
    return cleaned


class ReplayStatus(str, Enum):
    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    HARD_FAILURE = "hard_failure"
    ESCALATED = "escalated"


class StepOutcome(BaseModel):
    step_id: str
    action: str
    status: str
    duration_ms: float
    attempts: int = 1
    checkpoints: list[CheckpointResult] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class ReplayResult(BaseModel):
    status: ReplayStatus
    capability_id: str
    version: int
    code: str | None = None
    message: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[StepOutcome] = Field(default_factory=list)
    total_retries: int = 0
    duration_ms: float = 0.0
    evidence_ref: str | None = None
    run_id: str
