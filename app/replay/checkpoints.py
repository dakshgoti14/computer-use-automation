"""Executable checkpoint evaluation.

A replay step is only successful once every checkpoint attached to it
passes. Nothing here trusts "the click probably worked" - each kind maps to
one concrete, observable assertion.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.artifacts.schema import Checkpoint, CheckpointKind
from app.browser.surface import SurfaceAdapter


class CheckpointResult(BaseModel):
    checkpoint_id: str
    kind: CheckpointKind
    passed: bool
    detail: str


async def evaluate_checkpoint(
    checkpoint: Checkpoint,
    *,
    surface: SurfaceAdapter,
    current_url: str,
    page_text: str,
    extracted_value: str | None,
) -> CheckpointResult:
    if checkpoint.kind == CheckpointKind.ELEMENT_VISIBLE:
        assert checkpoint.target is not None
        ok = await surface.wait_for(checkpoint.target, timeout_ms=3000)
        return CheckpointResult(
            checkpoint_id=checkpoint.checkpoint_id,
            kind=checkpoint.kind,
            passed=ok,
            detail=f"target visible={ok} ({checkpoint.target.describe()})",
        )

    if checkpoint.kind == CheckpointKind.ELEMENT_NOT_VISIBLE:
        assert checkpoint.target is not None
        visible = await surface.wait_for(checkpoint.target, timeout_ms=1000)
        return CheckpointResult(
            checkpoint_id=checkpoint.checkpoint_id,
            kind=checkpoint.kind,
            passed=not visible,
            detail=f"target still visible={visible} ({checkpoint.target.describe()})",
        )

    if checkpoint.kind == CheckpointKind.URL_MATCHES:
        assert checkpoint.url_pattern is not None
        ok = re.search(checkpoint.url_pattern, current_url) is not None
        return CheckpointResult(
            checkpoint_id=checkpoint.checkpoint_id,
            kind=checkpoint.kind,
            passed=ok,
            detail=f"url={current_url!r} pattern={checkpoint.url_pattern!r}",
        )

    if checkpoint.kind == CheckpointKind.TEXT_CONTAINS:
        assert checkpoint.expected_text is not None
        ok = checkpoint.expected_text.lower() in page_text.lower()
        return CheckpointResult(
            checkpoint_id=checkpoint.checkpoint_id,
            kind=checkpoint.kind,
            passed=ok,
            detail=f"expected_text={checkpoint.expected_text!r} found={ok}",
        )

    if checkpoint.kind == CheckpointKind.VALUE_MATCHES_PATTERN:
        assert checkpoint.value_pattern is not None
        value = extracted_value or ""
        ok = re.match(checkpoint.value_pattern, value.strip()) is not None
        return CheckpointResult(
            checkpoint_id=checkpoint.checkpoint_id,
            kind=checkpoint.kind,
            passed=ok,
            detail=f"value={value!r} pattern={checkpoint.value_pattern!r}",
        )

    return CheckpointResult(
        checkpoint_id=checkpoint.checkpoint_id,
        kind=checkpoint.kind,
        passed=False,
        detail=f"Unhandled checkpoint kind {checkpoint.kind}",
    )
