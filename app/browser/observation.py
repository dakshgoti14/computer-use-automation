"""Normalized observation model handed to the LLM agent and stored as evidence.

The agent never sees raw HTML. Every surface implementation (currently just
Playwright) is responsible for reducing the live page down to this bounded,
structured shape so that (a) token usage stays predictable and (b) the
agent's decision logic never depends on a specific rendering engine.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MAX_VISIBLE_TEXT_CHARS = 2000
MAX_INTERACTIVE_ELEMENTS = 40


class InteractiveElement(BaseModel):
    """One actionable element on the page, described semantically."""

    element_id: str = Field(description="Stable index assigned for this observation")
    tag: str
    role: str | None = None
    accessible_name: str | None = None
    label: str | None = None
    test_id: str | None = None
    text: str | None = None
    input_type: str | None = None
    placeholder: str | None = None
    is_visible: bool = True
    is_disabled: bool = False


class FormField(BaseModel):
    name: str
    field_type: str
    label: str | None = None
    value: str | None = None
    required: bool = False


class Observation(BaseModel):
    """A bounded, structured snapshot of the current page state."""

    url: str
    title: str
    visible_text: str = Field(description="Truncated, whitespace-normalized body text")
    interactive_elements: list[InteractiveElement] = Field(default_factory=list)
    form_fields: list[FormField] = Field(default_factory=list)
    page_kind: Literal["unknown"] | str = "unknown"
    banner_messages: list[str] = Field(
        default_factory=list, description="Alert/flash/error banners visible on the page"
    )
    screenshot_ref: str | None = None
    truncated: bool = False

    def to_prompt_text(self) -> str:
        """Compact textual rendering used inside the LLM prompt."""

        lines = [f"URL: {self.url}", f"TITLE: {self.title}", f"PAGE_KIND: {self.page_kind}"]
        if self.banner_messages:
            lines.append("BANNERS: " + " | ".join(self.banner_messages))
        lines.append("VISIBLE_TEXT:")
        lines.append(self.visible_text)
        lines.append("INTERACTIVE_ELEMENTS:")
        for el in self.interactive_elements:
            descriptor = (
                f"  [{el.element_id}] tag={el.tag} role={el.role or '-'} "
                f"name={el.accessible_name or el.label or el.text or '-'} "
                f"test_id={el.test_id or '-'} disabled={el.is_disabled}"
            )
            lines.append(descriptor)
        if self.form_fields:
            lines.append("FORM_FIELDS:")
            for f in self.form_fields:
                lines.append(
                    f"  name={f.name} type={f.field_type} label={f.label or '-'} "
                    f"required={f.required}"
                )
        return "\n".join(lines)
