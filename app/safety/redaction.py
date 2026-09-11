"""Reusable secret/PII redaction for logs and evidence.

Honest scope statement (also repeated in README "Safety model"): this is a
pattern-based best-effort redactor, not a guarantee of perfect PII removal.
It reliably catches the shapes we explicitly test (API keys, bearer tokens,
passwords in form submissions, cookies, and full member/account numbers) but
it cannot catch novel or unstructured sensitive text embedded in free-form
page copy. Evidence review before sharing outside the team is still required
for anything beyond this demo.
"""

from __future__ import annotations

import re
from typing import Any

_REDACTED = "[REDACTED]"

_PATTERNS: list[re.Pattern[str]] = [
    # Common API key shapes: sk-..., AIza..., generic 32+ char hex/base64 keys
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"(?i)\bapi[_-]?key[\"'=:\s]+[A-Za-z0-9_\-\.]{12,}"),
    # Bearer / JWT-style tokens
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    # Passwords in form-encoded or key: value text
    re.compile(r'(?i)"?password"?\s*[:=]\s*"?[^\s,"&]{1,64}"?'),
    # Session cookies
    re.compile(r"(?i)\bsession(?:id)?=[A-Za-z0-9._\-%]{8,}"),
    # Full member/account numbers (this demo's member ids are 5 digits;
    # redact any bare 5+ digit id following the word "member"/"account")
    re.compile(r"(?i)\b(member|account)[_\s#-]*(id[_\s#-]*)?\d{5,}\b"),
]


def redact_text(value: str) -> str:
    """Return ``value`` with known-sensitive substrings replaced."""

    redacted = value
    for pattern in _PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


#: Field names whose *entire* value is redacted outright, regardless of shape.
_FULLY_REDACTED_KEYS = {
    "password",
    "api_key",
    "gemini_api_key",
    "authorization",
    "cookie",
    "session_token",
    "token",
    "secret",
}


#: Keys that, when present alongside them, mark a sibling "value"/"text" key
#: as sensitive even though "value" itself is not in _FULLY_REDACTED_KEYS.
#: Defense-in-depth for form-field-shaped observation data (see
#: app.browser.observation.FormField) - the primary fix is that the browser
#: extraction layer never captures password values at all; this catches any
#: other structurally-similar shape that slips through.
_SENSITIVE_TYPE_MARKERS = {"password"}
_VALUE_LIKE_KEYS = {"value", "text"}


def redact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact a structured payload before it is logged/persisted."""

    sibling_marks_sensitive = any(
        str(payload.get(k, "")).lower() in _SENSITIVE_TYPE_MARKERS
        for k in ("field_type", "input_type", "type")
    )

    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in _FULLY_REDACTED_KEYS or (
            sibling_marks_sensitive and key.lower() in _VALUE_LIKE_KEYS and value
        ):
            result[key] = _REDACTED
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        elif isinstance(value, list):
            result[key] = [
                redact_dict(v) if isinstance(v, dict) else redact_text(v) if isinstance(v, str) else v
                for v in value
            ]
        elif isinstance(value, str):
            result[key] = redact_text(value)
        else:
            result[key] = value
    return result
